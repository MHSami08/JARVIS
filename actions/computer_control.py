#computer_control.py
import json
import platform
import string
import subprocess
import sys

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import time
import random
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def _get_os() -> str:
    return _load_config().get("os_system", _platform_os()).lower()


def _get_api_key() -> str:
    # Ask the shared key ladder first so this follows the fallback order.
    try:
        from core import gemini
        k = gemini.api_key()
        if k:
            return k
    except Exception:
        pass
    return _load_config().get("gemini_api_key", "")

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "jarvis_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, **_WIN_HIDE,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _grounding():
    """The targeting layer, imported on use.

    Deferred so this module can be imported (by the action loader, at startup)
    without pulling in PyQt6 or the OCR engine, and so the coordinate layer is
    never loaded before DPI awareness has been declared.
    """
    from core import ui_grounding
    return ui_grounding


def _screen_find(description: str, window: str | None = None):
    """Find an element and return its best (x, y) in physical pixels.

    This replaces a version that asked a vision model for a normalised box on
    every single call, trusted whatever came back, and clicked. Three things
    were wrong with that and all three are fixed here:

    * The answer was never validated. A model replying in pixels, or in 0-1
      fractions, produced a coordinate that looked plausible and was wrong.
      `ui_grounding.parse_box` now infers the unit and rejects what it cannot
      place.
    * It was slow and cost a model call per click. The accessibility tree
      answers in ~10-40 ms with a rectangle Windows computed itself, and OCR
      covers the apps the tree cannot see — so the model is now the last resort
      rather than the only option.
    * Only the box centre survived, so nothing downstream could verify the click
      or draw the target. The whole `Candidate` is returned now.

    Returns a `Candidate`, or None when nothing could find the element.
    """
    try:
        return _grounding().resolve_one(description, window=window)
    except Exception as e:
        print(f"[ComputerControl] screen_find failed: {e}")
        return None


def _screen_candidates(description: str, window: str | None = None) -> list:
    """Every place the targeting layer thinks the element might be, best first.

    `_screen_find` throws all but the winner away, and the winner is sometimes
    the wrong one — the vision layer asked for a contact row and answered with
    the row above it. `resolve()` already returns the full list precisely so a
    caller can try, verify and move on; this is the caller doing that.
    """
    try:
        return _grounding().resolve(description, window=window)
    except Exception as e:
        print(f"[ComputerControl] screen_candidates failed: {e}")
        return []


def _hwnd_for_window(title_fragment: str) -> int:
    """The HWND of the first visible window whose title contains the fragment.

    Kept separate from `region_for_window` because raising a window needs the
    handle, not its rectangle, and the two are looked up from different sources.
    """
    if not title_fragment:
        return 0
    try:
        from core import ui_grounding
        for w in ui_grounding._visible_top_windows(limit=20):
            try:
                name = str(w.Name or "")
                if title_fragment.lower() in name.lower():
                    hwnd = ui_grounding.window_handle(w)
                    if hwnd:
                        return hwnd
            except Exception:
                continue
    except Exception:
        pass
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if title_fragment.lower() in (w.title or "").lower() and w.visible:
                return int(w._hWnd)
    except Exception:
        pass
    return 0


# Below this, a candidate is a guess rather than a location. Only the vision
# layer produces them, and only when its two passes disagreed.
_WEAK_CONF = 0.5
# How many candidates a single click will try before giving up. Small on
# purpose: the point is to recover from one wrong winner, not to click around
# the screen looking for something that is not there.
_MAX_ATTEMPTS = 3


def _attemptable(candidates: list) -> list:
    """The candidates worth actually clicking, best first.

    A verified click is cheap when it works and expensive when it does not — it
    costs a pause, a click and a screen comparison each time — so a run only
    walks as far as the candidates are plausible. Everything the UIA and OCR
    layers produce is exact enough to try; the vision layer's unconfirmed
    guesses are tried only when nothing better exists, because clicking a
    point that neither of its two passes agreed on is the behaviour that
    produced the misclicks in the first place.
    """
    strong = [c for c in candidates if c.confidence >= _WEAK_CONF]
    if strong:
        return strong[:_MAX_ATTEMPTS]
    return candidates[:_MAX_ATTEMPTS]


def _corroborate(description: str, candidates: list, window: str | None) -> list:
    """Give a weak candidate one cheap chance to be confirmed or replaced.

    The vision layer can return a low-confidence box — its coarse and fine looks
    disagreed. Rather than click it and find out, ask the accessibility tree
    again, which costs about forty milliseconds and no API call. If the tree
    knows a control matching the description, that answer is pixel-exact and
    replaces the guess outright; if it does not, the guess stands, because
    unreadable UI (Electron, canvas) is precisely why the vision layer exists.

    Returns the list unchanged when there is nothing weak in it, which is the
    common case.
    """
    if not candidates or candidates[0].confidence >= _WEAK_CONF:
        return candidates
    try:
        from core import ui_grounding
        exact = ui_grounding.find_by_uia(description, window=window)
    except Exception as e:
        print(f"[ComputerControl] corroboration failed: {e}")
        return candidates
    if not exact:
        return candidates
    print(f"[ComputerControl] '{description}': the vision guess at "
          f"({candidates[0].x},{candidates[0].y}) conf={candidates[0].confidence:.2f} "
          f"was replaced by an exact match {exact[0].label!r} at "
          f"({exact[0].x},{exact[0].y})")
    # The exact hits first, then whatever else was offered, so the retry loop
    # still has the vision reading to fall back on.
    seen = {(c.x, c.y) for c in exact}
    return exact + [c for c in candidates if (c.x, c.y) not in seen]


def _screen_click(description: str, button: str = "left", clicks: int = 1,
                  player=None, verify: bool = True, window: str | None = None) -> str:
    """Find an element, show where it is, click it, and check it worked.

    The reticle is drawn before the click so a wrong target is visible rather
    than surprising, and the screen is compared afterwards so a click that
    silently missed is reported as a failure instead of as success.
    """
    from core import screen_geometry as sg

    candidates = _screen_candidates(description, window=window)
    if not candidates:
        return f"Element not found on screen: '{description}'"

    # A weak candidate is a guess, and a guess is worth confirming before the
    # click rather than after it. Only the vision layer produces weak ones, and
    # only when its two passes disagreed — see `find_by_vision`. A cheap UIA
    # re-walk costs ~40 ms and either rules the guess out or promotes it.
    candidates = _corroborate(description, candidates, window)

    # Raise the window the element belongs to before clicking it.
    #
    # A click is delivered to whatever window is under the cursor, but a click
    # into a window that is behind another one — or that is not the foreground
    # window at all — often does not register as a real interaction. The
    # targeting layer reports which window it found the element in, so that
    # window is brought forward first. Skipping this is why a click can land
    # exactly on a button and still do nothing.
    raised = False
    first = candidates[0]
    if first.window:
        try:
            from core import ui_grounding
            hwnd = _hwnd_for_window(first.window)
            if hwnd:
                raised = ui_grounding.force_foreground(hwnd)
                if raised:
                    # Let the raise settle before the click. A window that is
                    # still animating into the foreground can move the element
                    # out from under a coordinate resolved a moment ago.
                    time.sleep(0.15)
        except Exception:
            raised = False

    # Try the candidates in order, and let the screen decide.
    #
    # This used to click the single best candidate and report failure if nothing
    # changed — so when the winner was wrong, the run ended there even though the
    # layer had already offered the right answer second. That is how a request
    # for one contact row clicked the row above it and then simply stopped.
    # Verification exists; it was just never given a second thing to try.
    #
    # At most three are attempted, and only candidates the layer has real
    # confidence in, so a genuinely absent element still fails in bounded time
    # rather than clicking its way around the screen.
    attempts = _attemptable(candidates)
    last: tuple | None = None

    for index, cand in enumerate(attempts):
        # Show the target before acting on it.
        if player is not None:
            try:
                player.show_target(cand.rect, label=description,
                                   detail=f"via {cand.source}", dwell_ms=1200)
                if hasattr(player, "wait_target_painted"):
                    player.wait_target_painted(0.4)
            except Exception:
                pass

        # Watch both the click's neighbourhood and the window it sits in. The
        # local region alone is too narrow — a click on a "+" button changes a
        # label elsewhere in the window, and scoring that as a miss would be
        # wrong. The window region alone is too loose, so the two are checked
        # together and the result says which one moved.
        watch = None
        if verify:
            pad = 70
            l, t, r, b = cand.rect
            local = (max(0, l - pad), max(0, t - pad),
                     (r - l) + pad * 2, (b - t) + pad * 2)
            watch = sg.watch_for(local)
            watch.snapshot()

        time.sleep(0.12)
        _click(x=cand.x, y=cand.y, button=button, clicks=clicks)

        if player is not None:
            try:
                player.hide_target()
            except Exception:
                pass

        if watch is None:
            return (f"Clicked '{description}' at ({cand.x}, {cand.y}) "
                    f"[{cand.source}] — found via {cand.label!r}")

        changed, frac, where = watch.changed()
        if changed:
            # A percentage for a large change, nothing for a small one: a single
            # character changing is well under 0.1% and would read as "0.0%",
            # which looks like a failure.
            pct = f" ({frac * 100:.0f}%)" if frac >= 0.01 else ""
            tried = (f" (after {index} earlier miss"
                     f"{'es' if index != 1 else ''})" if index else "")
            return (f"Clicked '{description}' at ({cand.x}, {cand.y}) "
                    f"[{cand.source}] — screen changed {where}{pct}{tried}")
        last = (cand, watch)
        if index + 1 < len(attempts):
            print(f"[ComputerControl] '{description}': nothing changed after "
                  f"clicking {cand.label!r} at ({cand.x},{cand.y}), trying the "
                  f"next candidate")

    cand, _ = last
    raised_note = "" if raised or not cand.window else \
        f" (could not raise '{cand.window}', so the click may not register)"
    extra = (f"; {len(attempts) - 1} other candidate"
             f"{'s' if len(attempts) != 2 else ''} tried too" if len(attempts) > 1
             else "")
    return (f"Clicked '{description}' at ({cand.x}, {cand.y}) "
            f"[{cand.source}] — but NOTHING CHANGED on screen, so the click may "
            f"have missed{extra}{raised_note}; "
            f"the element found was {cand.label!r}")


def _screen_drag(from_desc: str, to_desc: str, player=None) -> str:
    """Drag one on-screen element onto another.

    Both ends are found the same way a click target is, which is what makes this
    work on a target the user names rather than on raw coordinates they would
    have to know.
    """
    from core import screen_geometry as sg

    src = _screen_find(from_desc)
    if src is None:
        return f"Drag source not found: '{from_desc}'"
    dst = _screen_find(to_desc)
    if dst is None:
        return f"Drag destination not found: '{to_desc}'"

    if player is not None:
        try:
            player.show_target(src.rect, label=f"drag {from_desc}",
                               detail=f"to {to_desc}", dwell_ms=1200)
            if hasattr(player, "wait_target_painted"):
                player.wait_target_painted(0.4)
        except Exception:
            pass

    time.sleep(0.12)
    result = _drag(src.x, src.y, dst.x, dst.y)

    if player is not None:
        try:
            player.hide_target()
        except Exception:
            pass
    return f"{result} — '{from_desc}' [{src.source}] → '{to_desc}' [{dst.source}]"

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      to_description: drag destination description for screen_drag
      goal          : what to accomplish, for screen_agent
      max_steps     : step ceiling for screen_agent (default 12)
      dry_run       : bool, plan and aim but do not click (screen_agent)
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      cursor_pos    — where the mouse is right now
      screen_find   — find an element (returns x,y)
      screen_click  — find an element, show it, click it, verify it worked
      screen_drag   — drag one named element onto another
      screen_verify — find an element without clicking, to check it exists
      screen_agent  — pursue a goal autonomously, verifying each step
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}  {params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "cursor_pos":
            from core import screen_geometry as sg
            x, y = sg.cursor_pos()
            return f"Mouse is at ({x}, {y})"

        if action == "screen_find":
            cand = _screen_find(params.get("description", ""),
                                window=params.get("window") or None)
            if cand is None:
                return "NOT_FOUND"
            return f"{cand.x},{cand.y}"

        if action == "screen_verify":
            desc = params.get("description", "")
            cand = _screen_find(desc, window=params.get("window") or None)
            if cand is None:
                return f"'{desc}' is NOT on screen."
            return (f"'{desc}' is on screen at ({cand.x}, {cand.y}), "
                    f"found as {cand.label!r} via {cand.source} "
                    f"(confidence {cand.confidence:.2f}).")

        if action == "screen_click":
            return _screen_click(
                params.get("description", ""),
                button=params.get("button", "left"),
                clicks=2 if params.get("clicks") == 2 else 1,
                player=player,
                verify=params.get("verify", True) is not False,
                window=params.get("window") or None,
            )

        if action == "screen_drag":
            return _screen_drag(
                params.get("description", ""),
                params.get("to_description", ""),
                player=player,
            )

        if action == "screen_agent":
            goal = params.get("goal", "") or params.get("description", "")
            if not goal:
                return "screen_agent needs a 'goal' describing what to accomplish."
            from core import screen_agent
            ok, why = screen_agent.available()
            if not ok:
                return f"Cannot run the screen agent: {why}"
            try:
                max_steps = int(params.get("max_steps", screen_agent.DEFAULT_MAX_STEPS))
            except (TypeError, ValueError):
                max_steps = screen_agent.DEFAULT_MAX_STEPS
            run = screen_agent.run(
                goal,
                max_steps=max(1, min(max_steps, 40)),
                dry_run=bool(params.get("dry_run", False)),
                show_overlay=params.get("show_overlay", True) is not False,
                player=player,
                log=(lambda m: player.write_log(f"[Agent] {m}")) if player else None,
            )
            return run.summary()

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ❌ {action}: {e}")
        return f"computer_control '{action}' failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_control",
    "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | cursor_pos | screen_find | screen_click | screen_drag | screen_verify | screen_agent | random_data | user_data"
            },
            "text": {
                "type": "STRING",
                "description": "Text to type or paste"
            },
            "x": {
                "type": "INTEGER",
                "description": "X coordinate"
            },
            "y": {
                "type": "INTEGER",
                "description": "Y coordinate"
            },
            "keys": {
                "type": "STRING",
                "description": "Key combination e.g. 'ctrl+c'"
            },
            "key": {
                "type": "STRING",
                "description": "Single key e.g. 'enter'"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount (default: 3)"
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Seconds to wait"
            },
            "title": {
                "type": "STRING",
                "description": "Window title for focus_window"
            },
            "description": {
                "type": "STRING",
                "description": "Element description for screen_find/screen_click/screen_drag/screen_verify. Use the element's exact visible label or accessibility name, e.g. 'Save', 'File menu'."
            },
            "to_description": {
                "type": "STRING",
                "description": "Where to drag to, for screen_drag"
            },
            "goal": {
                "type": "STRING",
                "description": "What to accomplish, for screen_agent — a task like 'open Notepad and type hello', not a single click"
            },
            "max_steps": {
                "type": "INTEGER",
                "description": "Step ceiling for screen_agent (default 12, max 40)"
            },
            "dry_run": {
                "type": "BOOLEAN",
                "description": "For screen_agent: plan and aim at each target but do not click. Use to show the user what it would do first."
            },
            "window": {
                "type": "STRING",
                "description": "Optional window title fragment to search within, for screen_find/click/verify. Narrows the search and avoids matching the same word in another window."
            },
            "verify": {
                "type": "BOOLEAN",
                "description": "For screen_click: check the screen changed after clicking (default true)"
            },
            "type": {
                "type": "STRING",
                "description": "Data type for random_data"
            },
            "field": {
                "type": "STRING",
                "description": "Field for user_data: name|email|city"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": computer_control,
}
