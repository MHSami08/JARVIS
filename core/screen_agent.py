"""Autonomous screen operation: pursue a goal by acting, observing and verifying.

Everything else in this feature set answers "where is this element?". This
module answers "get this done" — it plans steps, finds each target, acts, and
then checks whether the action actually had the effect it was supposed to. The
checking is the part that makes it autonomous rather than merely scripted: an
agent that clicks and hopes is not driving the machine, it is throwing input at
it.

The loop, per step:

    resolve the target  ->  show the reticle  ->  act  ->  observe  ->  verify
                                                             |
                                          failed? -> re-resolve with the
                                                     failure as context,
                                                     bounded retries

Three things keep it from being dangerous:

**It is bounded in every dimension.** A step cap, a wall-clock deadline, and a
per-step retry cap. It cannot run forever, and it cannot retry forever.

**It stops and asks when it is stuck.** After the retries are exhausted it gives
up on that step and returns, rather than trying variations until something
happens to work. An agent that will not stop is worse than one that fails
cleanly.

**Every step is visible.** The reticle is drawn before each action and the step
log is returned, so what it did and why is inspectable after the fact.

`dry_run` plans and resolves without moving the mouse at all — the way to see
what it *would* do before letting it do it.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from core import screen_geometry as sg
from core import ui_grounding as ug

# Ceilings. These are the difference between an assistant and something that
# runs away with the mouse; they are deliberately low enough that a stuck run
# ends in seconds, not minutes.
DEFAULT_MAX_STEPS = 12
DEFAULT_TOTAL_TIMEOUT_S = 180.0
DEFAULT_MAX_RETRIES = 2

# How long to wait after an action before looking at the result. Short, because
# most UI responds immediately and waiting longer on every step makes a
# multi-step run feel broken; the verify step re-checks once if nothing changed.
SETTLE_S = 0.45
SETTLE_RETRY_S = 0.9


# ── Step model ───────────────────────────────────────────────────────────────

@dataclass
class Step:
    """One action the agent intends to take.

    `action` is a verb the executor understands: click, double_click,
    right_click, type, hotkey, press, scroll, wait, drag. `target` is the
    natural-language description used to find a click point; `text`/`keys` carry
    the payload for the input verbs.
    """
    action: str
    target: str = ""
    text: str = ""
    keys: str = ""
    to_target: str = ""          # drag destination
    amount: int = 3
    seconds: float = 1.0
    note: str = ""               # why this step exists — shown in the log
    expect: str = ""             # what should change, for verification

    @staticmethod
    def from_dict(d: dict) -> "Step":
        return Step(
            action=str(d.get("action", "")).strip().lower(),
            target=str(d.get("target", "") or "").strip(),
            text=str(d.get("text", "") or ""),
            keys=str(d.get("keys", "") or "").strip(),
            to_target=str(d.get("to_target", "") or "").strip(),
            amount=int(d.get("amount", 3) or 3),
            seconds=float(d.get("seconds", 1.0) or 1.0),
            note=str(d.get("note", "") or "").strip(),
            expect=str(d.get("expect", "") or "").strip(),
        )

    def describe(self) -> str:
        bits = [self.action]
        if self.target:
            bits.append(f"'{self.target}'")
        if self.text:
            bits.append(f"text={self.text[:30]!r}")
        if self.keys:
            bits.append(f"keys={self.keys}")
        if self.to_target:
            bits.append(f"-> '{self.to_target}'")
        return " ".join(bits)


@dataclass
class StepResult:
    index: int
    step: Step
    ok: bool
    detail: str = ""
    source: str = ""
    point: tuple[int, int] | None = None
    attempts: int = 1
    elapsed: float = 0.0

    def line(self) -> str:
        mark = "OK " if self.ok else "FAIL"
        where = f" @{self.point}" if self.point else ""
        src = f" [{self.source}]" if self.source else ""
        retry = f" (attempt {self.attempts})" if self.attempts > 1 else ""
        return f"  {self.index}. [{mark}] {self.step.describe()}{where}{src}{retry} — {self.detail}"


# ── Planning ─────────────────────────────────────────────────────────────────

_PLAN_PROMPT = """You are driving a Windows computer to accomplish a goal for the user.

GOAL: {goal}

{context}

Break the goal into the smallest number of concrete steps. Each step is ONE action.

Available actions:
  click          - click an element; set "target" to a short description of what to click
  double_click   - double-click an element
  right_click    - right-click an element
  type           - type text; set "text"
  hotkey         - press a key combination; set "keys" e.g. "ctrl+s"
  press          - press one key; set "keys" e.g. "enter"
  scroll         - scroll the wheel; set "amount" (negative scrolls up)
  wait           - wait; set "seconds"
  drag           - drag; set "target" (source) and "to_target" (destination)

Rules:
- Use the accessibility name or the visible label as "target" — the exact text
  on the button is the best description, not a paraphrase of it.
- Prefer a keyboard shortcut over clicking through menus when one exists.
- Add a "note" saying why each step is needed.
- Do NOT add steps to verify your own work; verification is automatic.
- Stop as soon as the goal is met.

Reply with ONLY a JSON object, no prose:
{{"steps": [{{"action": "click", "target": "Save", "note": "open the save dialog"}}]}}
"""


def plan(goal: str, context: str = "", tier: str = "gemini-2.5-flash",
         timeout_ms: int = 25_000) -> list[Step]:
    """Ask the model to break a goal into steps.

    The plan is a suggestion, not a contract: each step is resolved and verified
    independently, so a plan that names an element that is not there fails at
    that step rather than derailing the run.
    """
    from core import gemini

    prompt = _PLAN_PROMPT.format(goal=goal, context=context)
    try:
        text = gemini.text(prompt, tier=tier, timeout_ms=timeout_ms) or ""
    except Exception as e:
        print(f"[Agent] planning failed: {e}")
        return []

    steps = _parse_steps(text)
    if steps:
        print(f"[Agent] planned {len(steps)} step(s) for: {goal}")
    else:
        print(f"[Agent] could not parse a plan from: {text[:200]!r}")
    return steps


def _parse_steps(text: str) -> list[Step]:
    """Pull the step list out of a model reply, tolerantly.

    Models wrap JSON in prose, in fences, or in a trailing explanation often
    enough that requiring a clean object would fail most of the time. The first
    balanced-looking object that contains a "steps" key wins.
    """
    if not text:
        return []
    cleaned = text.strip()
    # Strip a fenced block if there is one.
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    data = None
    try:
        data = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if data is None:
        return []

    if isinstance(data, dict):
        raw = data.get("steps") or data.get("plan") or []
    elif isinstance(data, list):
        raw = data
    else:
        return []

    out: list[Step] = []
    for item in raw:
        if isinstance(item, dict):
            s = Step.from_dict(item)
            if s.action:
                out.append(s)
    return out


# ── Acting ───────────────────────────────────────────────────────────────────

def _hwnd_for_window(title_fragment: str) -> int:
    """The HWND of the first visible window whose title contains the fragment."""
    if not title_fragment:
        return 0
    try:
        for w in ug._visible_top_windows(limit=20):
            try:
                if title_fragment.lower() in str(w.Name or "").lower():
                    hwnd = ug.window_handle(w)
                    if hwnd:
                        return hwnd
            except Exception:
                continue
    except Exception:
        pass
    return 0


def _act(step: Step, point: tuple[int, int] | None,
         second: tuple[int, int] | None = None) -> str:
    """Perform one step's input. Returns a human-readable result.

    Imported lazily so this module can be imported (and planned with) on a
    machine where pyautogui is absent, and so the import does not drag
    pyautogui's DPI call in before Qt has started.
    """
    try:
        import pyautogui
    except ImportError:
        return "pyautogui is not installed"
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02

    a = step.action
    try:
        if a in ("click", "left_click", "double_click", "right_click"):
            if point is None:
                return "no target found"
            button = "right" if a == "right_click" else "left"
            clicks = 2 if a == "double_click" else 1
            pyautogui.click(point[0], point[1], button=button, clicks=clicks)
            return f"clicked {point}"
        if a == "move":
            if point is None:
                return "no target found"
            pyautogui.moveTo(point[0], point[1], duration=0.2)
            return f"moved to {point}"
        if a == "drag":
            if point is None or second is None:
                return "drag needs both a source and a destination"
            pyautogui.moveTo(point[0], point[1], duration=0.2)
            pyautogui.dragTo(second[0], second[1], duration=0.5, button="left")
            return f"dragged {point} -> {second}"
        if a == "type":
            if not step.text:
                return "nothing to type"
            # typewrite cannot produce characters outside the keyboard layout;
            # the clipboard path in computer_control handles those, and this is
            # the same trick.
            if len(step.text) > 20:
                try:
                    import pyperclip
                    pyperclip.copy(step.text)
                    pyautogui.hotkey("ctrl", "v")
                    return f"pasted {len(step.text)} chars"
                except Exception:
                    pass
            pyautogui.typewrite(step.text, interval=0.02)
            return f"typed {step.text[:30]!r}"
        if a == "hotkey":
            if not step.keys:
                return "no keys given"
            keys = [k.strip() for k in re.split(r"[+\-]", step.keys) if k.strip()]
            pyautogui.hotkey(*keys)
            return f"pressed {'+'.join(keys)}"
        if a == "press":
            if not step.keys:
                return "no key given"
            pyautogui.press(step.keys.strip())
            return f"pressed {step.keys}"
        if a == "scroll":
            pyautogui.scroll(step.amount)
            return f"scrolled {step.amount}"
        if a == "wait":
            time.sleep(max(0.0, min(step.seconds, 10.0)))
            return f"waited {step.seconds}s"
        return f"unknown action {a!r}"
    except Exception as e:
        return f"{a} failed: {type(e).__name__}: {e}"


# ── Verifying ────────────────────────────────────────────────────────────────

def _watch_region(point: tuple[int, int] | None,
                  rect: tuple[int, int, int, int] | None,
                  pad: int = 90) -> tuple[int, int, int, int]:
    """The area to watch for a change after an action.

    Around the click point, not the whole screen: a change anywhere would be
    satisfied by an unrelated animation — a clock ticking, a video playing — and
    the agent would believe it had succeeded. Looking at the neighbourhood of
    the thing it touched is what makes the check mean something.
    """
    if rect is not None:
        l, t, r, b = rect
        cx, cy = (l + r) // 2, (t + b) // 2
        w = max(r - l, 40) + pad * 2
        h = max(b - t, 40) + pad * 2
    elif point is not None:
        cx, cy = point
        w = h = pad * 2
    else:
        cx, cy = sg.primary().width // 2, sg.primary().height // 2
        w = h = 200

    vd = sg.virtual_desktop()
    l = max(vd.left, cx - w // 2)
    t = max(vd.top, cy - h // 2)
    w = min(w, vd.right - l)
    h = min(h, vd.bottom - t)
    return (l, t, max(4, w), max(4, h))


def _verify(watch, expect: str) -> tuple[bool, str]:
    """Did the action have an effect?

    A pixel comparison is used rather than a model call because it is instant,
    free, and decisive for the common case — a button that depressed, a menu
    that opened, a dialog that appeared all change pixels. It cannot tell
    *whether the right thing* happened, which is what `expect` and the goal are
    for; it can tell that *something* did, which is what catches a click that
    silently missed.

    The watch covers both the click's neighbourhood and the window it is in.
    Watching only the neighbourhood was tried and was wrong: clicking a "+"
    button updates a label elsewhere in the window, so a click that worked was
    scored as a failure and retried — and the retry clicked again, which is how
    a two-click goal ended up clicking four times.
    """
    if watch is None:
        return True, "no before-image; assumed ok"

    changed, frac, where = watch.changed(settle_s=SETTLE_S, retry_s=SETTLE_RETRY_S)
    if changed:
        # Report whichever is more informative: a percentage for a big change,
        # a pixel count for a small one, since a single character changing is
        # well under 0.1% and would read as "0.0%" otherwise.
        if frac >= 0.01:
            return True, f"screen changed {where} ({frac * 100:.0f}%)"
        return True, f"screen changed {where}"
    if expect:
        return False, f"nothing changed where '{expect}' should have"
    return False, "nothing changed on screen"


# ── The loop ─────────────────────────────────────────────────────────────────

@dataclass
class AgentRun:
    goal: str
    results: list[StepResult] = field(default_factory=list)
    ok: bool = False
    stopped: str = ""
    elapsed: float = 0.0

    def summary(self) -> str:
        lines = [f"Goal: {self.goal}"]
        lines += [r.line() for r in self.results]
        if self.stopped:
            lines.append(f"  Stopped: {self.stopped}")
        done = sum(1 for r in self.results if r.ok)
        lines.append(f"  {done}/{len(self.results)} steps succeeded "
                     f"in {self.elapsed:.1f}s")
        return "\n".join(lines)


def run(goal: str,
        max_steps: int = DEFAULT_MAX_STEPS,
        total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        dry_run: bool = False,
        show_overlay: bool = True,
        player=None,
        speak: Callable[[str], None] | None = None,
        context: str = "",
        log: Callable[[str], None] | None = None) -> AgentRun:
    """Plan a goal and carry it out, verifying each step.

    `player` is the UI facade (`JarvisUI`) when there is one; it is used to draw
    the targeting reticle. `log` receives one line per step, so a run is
    traceable in the HUD as it happens rather than only in the returned summary.
    """
    started = time.monotonic()
    run_state = AgentRun(goal=goal)

    def emit(msg: str) -> None:
        print(f"[Agent] {msg}")
        if log:
            try:
                log(msg)
            except Exception:
                pass

    emit(f"goal: {goal}{' (dry run)' if dry_run else ''}")

    steps = plan(goal, context=context)
    if not steps:
        run_state.stopped = "could not produce a plan"
        run_state.elapsed = time.monotonic() - started
        return run_state

    for i, step in enumerate(steps[:max_steps], start=1):
        if time.monotonic() - started > total_timeout_s:
            run_state.stopped = f"hit the {total_timeout_s:.0f}s time limit"
            break

        t0 = time.monotonic()
        result = _run_step(i, step, dry_run=dry_run, show_overlay=show_overlay,
                           max_retries=max_retries, player=player,
                           goal=goal, emit=emit)
        result.elapsed = time.monotonic() - t0
        run_state.results.append(result)
        emit(result.line().strip())

        if not result.ok:
            # Stop rather than improvise. An agent that keeps trying variations
            # after a failed step is the one that clicks something destructive
            # by accident.
            run_state.stopped = f"step {i} failed: {result.detail}"
            break

    run_state.ok = bool(run_state.results) and all(r.ok for r in run_state.results)
    run_state.elapsed = time.monotonic() - started
    emit(f"finished: {run_state.summary().splitlines()[-1].strip()}")
    return run_state


def _run_step(index: int, step: Step, dry_run: bool, show_overlay: bool,
              max_retries: int, player, goal: str, emit) -> StepResult:
    """Resolve, act, verify — and retry by looking again at a DIFFERENT guess.

    A retry re-resolves the target from scratch, never repeating the same action
    at the same stale coordinates: the usual reason a step failed is that the
    screen moved between finding the element and clicking it, so repeating the
    click at the old point would fail again.

    Re-resolving alone was not enough, though, and the shortfall is the one that
    produced the "it clicked the row above" report. `resolve()` is deterministic,
    so looking again returned the same winner — and when the winner was the wrong
    one, every retry failed identically and the loop spent its budget proving the
    same mistake. Each retry now also steps to the next candidate in the ranked
    list, so a wrong first choice costs one attempt rather than the whole step.
    """
    res = StepResult(index=index, step=step, ok=False)

    # A step with no target acts on whatever already has focus.
    needs_target = step.action in ("click", "left_click", "double_click",
                                   "right_click", "move", "drag")

    attempt = 0
    # How far down the candidate list a retry is allowed to walk.
    #
    # The retry used to re-run `resolve()` from scratch, which is deterministic:
    # it returned the same winner every time, so a step whose winner was wrong
    # failed identically on every attempt and the loop burned its retries
    # proving it. `resolve()` already returns the whole ranked list for exactly
    # this reason — a caller that clicks, sees nothing happen and tries the next
    # one has somewhere to go. This is that caller.
    #
    # Bounded, because a target that is genuinely absent should fail rather than
    # click its way around the screen: the first attempt takes the best
    # candidate, and each retry takes the next one, never cycling.
    pick = 0
    while True:
        attempt += 1
        res.attempts = attempt

        point = rect = None
        second = None
        source = ""
        window = ""

        if needs_target:
            hits = ug.resolve(step.target or step.text, allow_vision=not dry_run)
            if not hits:
                res.detail = f"could not find '{step.target}' on screen"
                if attempt <= max_retries and not dry_run:
                    time.sleep(0.4)
                    continue
                return res
            # Walk down the list on each retry, and say so when the step is
            # running on something other than the layer's first choice.
            if pick >= len(hits):
                res.detail = (f"'{step.target}' was found but none of the "
                              f"{len(hits)} candidate"
                              f"{'s' if len(hits) != 1 else ''} took effect")
                return res
            best = hits[pick]
            if pick:
                emit(f"  step {index}: retrying with candidate {pick + 1} of "
                     f"{len(hits)} — {best.label!r} at {best.centre}")
            point, rect, source = best.centre, best.rect, best.source
            window = best.window or ""
            res.point, res.source = point, source

            if step.action == "drag":
                dest = ug.resolve_one(step.to_target, allow_vision=not dry_run)
                if dest is None:
                    res.detail = f"could not find drag destination '{step.to_target}'"
                    if attempt <= max_retries and not dry_run:
                        time.sleep(0.4)
                        continue
                    return res
                second = dest.centre

        # Bring the element's window to the front before acting on it.
        #
        # A click is delivered to whatever is under the cursor, but a click into
        # a window that is behind another one frequently does not register as a
        # real interaction. Without this the agent aims perfectly, the click
        # goes nowhere, and the step is scored as a failure it will then retry —
        # the retry also doing nothing. It is also what makes the verification
        # meaningful: the window being watched is the one being driven, so a
        # change seen there is really this step's doing.
        if window and not dry_run:
            try:
                hwnd = _hwnd_for_window(window)
                if hwnd:
                    ug.force_foreground(hwnd)
                    time.sleep(0.12)
            except Exception:
                pass

        if show_overlay and player is not None and point is not None:
            try:
                badge = "DRY RUN" if dry_run else ""
                player.show_target(rect, label=step.target or step.action,
                                   badge=badge, detail=f"via {source}", dwell_ms=None)
                if hasattr(player, "wait_target_painted"):
                    player.wait_target_painted(0.4)
            except Exception:
                pass

        if dry_run:
            res.ok = True
            res.detail = f"would {step.action}" + (f" at {point}" if point else "")
            _clear(player, show_overlay)
            return res

        # Snapshot the watched areas BEFORE acting, so the after-image has
        # something to differ from. The wide region is the foreground window,
        # which is what catches an action whose effect appears away from the
        # thing that was clicked.
        watch = None
        if point is not None or rect is not None:
            # Watch the window the element was found in — not whatever happens
            # to be foreground. Those are the same window now that it has been
            # raised, but naming it explicitly keeps the two from drifting apart
            # if the raise fails, and a watch on the wrong window would report a
            # change made by something else.
            wide = ug.region_for_window(window) if window else None
            watch = sg.watch_for(_watch_region(point, rect), wide=wide)
            watch.snapshot()

        detail = _act(step, point, second)
        _clear(player, show_overlay)

        ok, why = _verify(watch, step.expect)
        res.ok = ok
        res.detail = f"{detail}; {why}"

        if ok or attempt > max_retries:
            return res
        # Advance to the next candidate as well as retrying, so the next attempt
        # is a different guess rather than the same one again.
        pick += 1
        emit(f"  step {index} did not take effect, trying the next candidate "
             f"(attempt {attempt + 1})")


def _clear(player, show_overlay: bool) -> None:
    """Take the reticle down before the screen is examined.

    Essential, not cosmetic: the reticle is a real window and it appears in
    captures (translucency forces WS_EX_LAYERED, which makes the capture-
    exclusion API fail). Leaving it up would mean the before/after comparison
    saw the reticle appear and vanish, and every step would look like it had
    changed something.
    """
    if not show_overlay or player is None:
        return
    try:
        player.hide_target()
    except Exception:
        pass
    time.sleep(0.05)


def available() -> tuple[bool, str]:
    """Whether the agent can run, and why not if it cannot."""
    try:
        import pyautogui  # noqa: F401
    except ImportError:
        return False, "pyautogui is not installed"
    if not ug.uia_available() and not ug.ocr_available():
        return False, "no targeting layer is available (need uiautomation or OCR)"
    return True, ""
