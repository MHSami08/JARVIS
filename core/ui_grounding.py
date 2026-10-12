"""Turn "the Save button" into an exact pixel — cheapest method first.

The old finder asked a vision model for a bounding box on every single click.
That is slow (1-3 s), costs a model call per click, and — because the answer was
never validated — could land anywhere. This module answers the same question
with a ladder of strategies, from free and exact to expensive and approximate:

    Layer 0  accessibility tree   ~10-40 ms   no model   pixel-exact
    Layer 1  OCR text match      ~50-150 ms   no model   exact for text
    Layer 2  vision grounding      1-3 s      model      approximate

The ordering is the whole point. A control the accessibility tree knows about
has a rectangle Windows itself computed, so a click at its centre cannot miss.
Most desktop UI — buttons, menus, fields, tabs, list items — is in that tree.
Electron, Chrome and canvas apps expose almost nothing, and that is what OCR is
for. Only when neither can see it does a model get asked, and by then the search
is usually already narrowed to a window, which makes the model's answer far more
likely to be right than a blind full-screen guess.

Nothing here moves the mouse. It answers where things are; `computer_control`
does the clicking.
"""

from __future__ import annotations

import ctypes
import re
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

from core import screen_geometry as sg

_IS_WINDOWS = sys.platform == "win32"

# ── Control types worth aiming at ────────────────────────────────────────────
# A tree walk sees hundreds of layout containers, panes and text labels that
# nobody would ever ask to click. Restricting the search to these keeps it fast
# and, more importantly, stops a container's huge rectangle from beating the
# small button inside it.
_CLICKABLE_TYPES = {
    "ButtonControl", "MenuItemControl", "TabItemControl", "ListItemControl",
    "CheckBoxControl", "RadioButtonControl", "ComboBoxControl", "EditControl",
    "HyperlinkControl", "TreeItemControl", "DataItemControl", "SplitButtonControl",
    "HeaderItemControl", "TextControl", "ImageControl", "DocumentControl",
    "ThumbControl", "SliderControl", "SpinnerControl", "CustomControl",
    "GroupControl", "ToolBarControl", "MenuControl", "MenuBarControl",
}

# Types that are almost always scaffolding rather than a target. A description
# matching one of these is a much weaker signal than one matching a button.
_PASSIVE_TYPES = {"PaneControl", "GroupControl", "CustomControl", "DocumentControl"}


# ── Result ───────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """One place an element might be, with how it was found and how sure we are.

    `rect` is a physical (left, top, right, bottom) box; `x`/`y` are its centre,
    already rounded, and are what a click should use. `source` is the layer that
    produced it — "uia", "ocr" or "vision" — and is worth logging, because a run
    that is suddenly all "vision" means the fast paths have broken.

    `label` is the element's own name as the OS or OCR saw it, which is what
    makes a wrong answer diagnosable: if the model clicked the wrong thing, the
    label says what it actually found.
    """
    x: int
    y: int
    rect: tuple[int, int, int, int]
    source: str
    confidence: float = 1.0
    label: str = ""
    control_type: str = ""
    window: str = ""

    @property
    def centre(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def size(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return r - l, b - t

    def __str__(self) -> str:
        l, t, r, b = self.rect
        return (f"{self.label or '?'!r} @ ({self.x},{self.y}) "
                f"[{l},{t},{r},{b}] via {self.source} conf={self.confidence:.2f}")


def _centre(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    l, t, r, b = rect
    # round, not int: int() truncates toward zero and biases every click half a
    # pixel up and to the left, which is a systematic miss on small targets.
    return round((l + r) / 2), round((t + b) / 2)


def _clamp_to_screen(c: Candidate) -> Candidate:
    """Keep a candidate on a real display.

    A tree can report a control at a negative or off-screen coordinate for a
    minimised or scrolled-away window. Clicking there does nothing, or hits
    whatever happens to be at that spot, so such a candidate is dropped rather
    than clamped into something plausible-looking but wrong.
    """
    vd = sg.virtual_desktop()
    l, t, r, b = c.rect
    if r <= vd.left or b <= vd.top or l >= vd.right or t >= vd.bottom:
        return None  # type: ignore[return-value]
    l = max(l, vd.left)
    t = max(t, vd.top)
    r = min(r, vd.right)
    b = min(b, vd.bottom)
    if r - l < 1 or b - t < 1:
        return None  # type: ignore[return-value]
    cx, cy = _centre((l, t, r, b))
    c.rect = (l, t, r, b)
    c.x, c.y = cx, cy
    return c


# ── Text matching ────────────────────────────────────────────────────────────

_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Words that describe the KIND of thing rather than which one. "the save button"
# and "save" have to score the same against a control named "Save", so these are
# dropped from the description before matching.
_STOPWORDS = {
    "the", "a", "an", "this", "that", "click", "press", "tap", "on", "in", "at",
    "to", "of", "for", "button", "btn", "icon", "link", "field", "box", "menu",
    "item", "option", "tab", "please", "then", "and", "it", "its", "with",
}


def _norm(s: str) -> str:
    return " ".join(_SPLIT_RE.split((s or "").lower())).strip()


def _tokens(s: str, drop_stopwords: bool = True) -> list[str]:
    toks = [t for t in _SPLIT_RE.split((s or "").lower()) if t]
    if drop_stopwords:
        kept = [t for t in toks if t not in _STOPWORDS]
        # If the description was nothing BUT stopwords ("the button"), keep them
        # — a weaker signal beats no signal.
        return kept or toks
    return toks


def _similarity(description: str, label: str) -> float:
    """How well a description matches an element's own name, 0..1.

    Three signals, because UI names vary wildly: an exact/substring hit ("save"
    vs "Save"), token overlap ("save file" vs "Save"), and character-level
    similarity for typos and abbreviations ("sve" vs "Save"). The best of the
    three is used — a control only has to match convincingly one way.
    """
    d, l = _norm(description), _norm(label)
    if not d or not l:
        return 0.0
    if d == l:
        return 1.0
    if d in l or l in d:
        # Substring hits scale with how much of the longer string was covered,
        # so "save" vs "Save as" (0.57) ranks below "save" vs "Save" (1.0).
        #
        # The length floor is load-bearing. Without it, OCR reading a stray "A"
        # anywhere on screen scores 0.82 against "Plan mode", because the letter
        # a is inside the word plan — and a one-character OCR fragment would
        # outrank every real match. Short labels like "OK" are handled by the
        # token path below, which compares whole words instead.
        short = d if len(d) <= len(l) else l
        if len(short) >= 3:
            return 0.80 + 0.20 * (len(short) / max(len(d), len(l)))

    dt, lt = set(_tokens(description)), set(_tokens(label))
    if dt and lt:
        overlap = len(dt & lt) / len(dt | lt)
        # A description whose every token appears in the label is a strong hit
        # even when the label carries extra words.
        if dt <= lt:
            overlap = max(overlap, 0.75)
        if overlap:
            return 0.45 + 0.45 * overlap

    return SequenceMatcher(None, d, l).ratio() * 0.6


# ── Layer 0: accessibility tree ──────────────────────────────────────────────

def _uia_module():
    try:
        import uiautomation  # noqa: F401
        return uiautomation
    except ImportError:
        return None


def _foreground_window_uia():
    """The window the user is actually looking at, as a UIA control."""
    a = _uia_module()
    if a is None:
        return None
    try:
        fg = a.GetForegroundControl()
        if fg is None:
            return None
        # GetForegroundControl can return a child (an edit field, a menu item).
        # Walk up to the enclosing window so the walk covers the whole app.
        node = fg
        for _ in range(12):
            if node.ControlTypeName == "WindowControl":
                return node
            parent = node.GetParentControl()
            if parent is None:
                return fg
            node = parent
        return fg
    except Exception:
        return None


def _walk_controls(root, max_depth: int = 12, max_nodes: int = 2500,
                   deadline: float | None = None) -> list:
    """Depth-first walk of a UIA subtree, bounded in every dimension.

    The caps are not paranoia: a browser or an IDE can expose tens of thousands
    of nodes, and an unbounded walk on the UI thread would freeze the assistant
    for seconds. Depth, node count and wall clock are all limited, and whatever
    was collected before a limit hit is still returned.
    """
    out: list = []
    stack = [(root, 0)]
    while stack:
        if len(out) >= max_nodes:
            break
        if deadline is not None and time.monotonic() > deadline:
            break
        node, depth = stack.pop()
        out.append(node)
        if depth >= max_depth:
            continue
        try:
            children = node.GetChildren()
        except Exception:
            continue
        for ch in reversed(children):
            stack.append((ch, depth + 1))
    return out


# Titles of JARVIS's own windows, so they can be skipped. Matched
# case-insensitively as a substring — the HUD's title carries the assistant's
# configured name, which is "JARVIS" unless the user renamed it.
_OWN_WINDOW_MARKERS = ("jarvis", "brahma")


def _is_own_window(w) -> bool:
    """Is this window one of JARVIS's own?

    Skipping them matters because the HUD is always open and always nearby, so a
    generic description like "Save" could otherwise match a control in the
    assistant's own interface instead of the app the user meant.

    The calibration probe is deliberately NOT listed: it is a test fixture that
    exists to be clicked, so excluding it would make the self-test unable to
    find its own targets.
    """
    try:
        name = str(w.Name or "").lower()
    except Exception:
        return False
    return any(m in name for m in _OWN_WINDOW_MARKERS)


def window_handle(w) -> int:
    """A window control's native HWND, or 0."""
    try:
        return int(w.NativeWindowHandle or 0)
    except Exception:
        return 0


# Windows shell surfaces that expose clickable controls but are not
# WindowControls. Matched on the Win32 class name, which is stable and
# documented, rather than on the accessible name, which is localised — a
# Turkish or German Windows still calls it Shell_TrayWnd.
_SHELL_CLASSES = {
    "shell_traywnd",          # the taskbar
    "shell_secondarytraywnd",  # the taskbar on a secondary monitor
    "notifyiconoverflowwindow",  # the hidden-icons flyout
}

# The desktop and the program manager are shell surfaces too, but they are a
# wallpaper and a right-click menu, not something to aim a click at. Listing
# them as exclusions keeps the walk from wandering into the desktop's icon grid
# when the user asks for something by a name a desktop shortcut happens to have.
_SHELL_EXCLUDED = {
    "progman", "workerw", "shelltabwindowclass",
}


def _is_shell_surface(w) -> bool:
    """Is this a shell surface worth searching — the taskbar, essentially?"""
    try:
        cls = str(w.ClassName or "").strip().lower()
    except Exception:
        return False
    if not cls:
        return False
    if cls in _SHELL_EXCLUDED:
        return False
    if cls in _SHELL_CLASSES:
        return True
    # The taskbar's own children (its toolbars) are found by walking the parent
    # we already accepted, so nothing else needs to match here.
    return False


def _visible_top_windows(limit: int = 12) -> list:
    """Visible top-level windows, foreground first.

    The foreground window is searched first because it is what the user is
    looking at, and its controls are the likeliest match. But searching ONLY it
    is wrong, and this is the fix for a real failure: JARVIS's own HUD holds
    focus while the user talks to it, so a foreground-only search looks through
    the assistant's own interface and cannot see the app being driven. An
    instruction to click something in Notepad would find nothing, fall through
    to the vision layer, and miss.

    So every visible top-level window is searched, in order. Ordering still
    matters — it decides which match wins when two windows contain the same
    label — but a target in a background window is now findable at all.
    """
    a = _uia_module()
    if a is None:
        return []
    try:
        root = a.GetRootControl()
        children = root.GetChildren()
    except Exception:
        return []

    fg = _foreground_window_uia()
    fg_handle = None
    if fg is not None:
        try:
            fg_handle = int(fg.NativeWindowHandle or 0)
        except Exception:
            fg_handle = None

    out: list = []
    shell: list = []
    for w in children:
        try:
            ctype = str(w.ControlTypeName or "")
            # WindowControl is a normal application window. The shell surfaces —
            # the taskbar, the desktop, the system tray — are not WindowControls
            # at all: the taskbar is a PaneControl with class Shell_TrayWnd, and
            # requiring WindowControl skipped it entirely.
            #
            # That mattered a great deal. Taskbar icons are the most-clicked
            # thing a desktop assistant is asked for, and with the taskbar
            # invisible to this layer every such request fell through to the
            # vision model — slow, and measurably inaccurate, which is what
            # produced clicks landing on the icon to the LEFT of the one asked
            # for. The taskbar exposes every icon's exact rectangle, so this one
            # filter was the difference between exact and wrong.
            is_window = ctype == "WindowControl"
            is_shell = (ctype in ("PaneControl", "ToolBarControl")
                        and _is_shell_surface(w))
            if not (is_window or is_shell):
                continue
            # IsOffscreen is the property that exists; there is no IsVisible on
            # a uiautomation Control. Testing for one that is not there raised
            # AttributeError into the except below, which silently emptied this
            # whole list — and a UIA search that finds nothing looks exactly
            # like a UIA search that was never run.
            if w.IsOffscreen:
                continue
            br = w.BoundingRectangle
            if br is None:
                continue
            width, height = br.right - br.left, br.bottom - br.top
            if is_window:
                # A real window smaller than this is a tooltip or a shadow, not
                # something to drive.
                if width < 60 or height < 60:
                    continue
            else:
                # The taskbar is 40 px tall on a 1080p display, so the window
                # size floor above would have rejected it even once the type
                # check allowed it. Shell surfaces only need to be non-empty.
                if width < 40 or height < 8:
                    continue
            # Never target JARVIS's own interface. A request to "click Save"
            # should reach the app being driven, not a control in the assistant
            # that happens to share the word — and the assistant's own window is
            # exactly the one that is always open and always nearby.
            if _is_own_window(w):
                continue
            (out if is_window else shell).append(w)
        except Exception:
            continue

    if fg_handle:
        def rank(w):
            try:
                return 0 if int(w.NativeWindowHandle or 0) == fg_handle else 1
            except Exception:
                return 1
        out.sort(key=rank)

    # Application windows are searched before the shell. The shell is always on
    # screen, so putting it first would let a taskbar icon outrank a button of
    # the same name in the app actually being used — and "WhatsApp" as a taskbar
    # icon and "WhatsApp" as a button inside a page are different targets.
    #
    # The shell keeps its own share of the budget rather than being appended and
    # sliced: with a dozen windows open, appending would drop the taskbar off
    # the end of the list entirely and reintroduce the very bug this fixes.
    shell_slots = max(1, min(len(shell), max(2, limit // 4)))
    return out[:max(0, limit - shell_slots)] + shell[:shell_slots]


def _score_nodes(nodes, description: str, min_confidence: float,
                 win_name: str) -> list[tuple[float, Candidate]]:
    """Score every node in a walked subtree against the description."""
    scored: list[tuple[float, Candidate]] = []
    for node in nodes:
        try:
            ctype = str(node.ControlTypeName or "")
            if ctype and ctype not in _CLICKABLE_TYPES:
                continue
            name = str(node.Name or "")
            if not name.strip():
                continue
            # A control's Name is not always its visible label — but for
            # buttons, menu items and links it is, and those are the targets
            # that matter. AutomationId catches the rest ("btnSave").
            aid = ""
            try:
                aid = str(node.AutomationId or "")
            except Exception:
                pass

            score = _similarity(description, name)
            if aid:
                score = max(score, _similarity(description, aid) * 0.9)
            if score < min_confidence:
                continue

            br = node.BoundingRectangle
            if br is None:
                continue
            rect = (int(br.left), int(br.top), int(br.right), int(br.bottom))
            if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
                continue

            # A passive container matching the description should lose to the
            # real control inside it.
            if ctype in _PASSIVE_TYPES:
                score *= 0.75
            # Enabled and on-screen controls are the ones a click can reach.
            try:
                if not node.IsEnabled:
                    score *= 0.5
            except Exception:
                pass
            try:
                if node.IsOffscreen:
                    continue
            except Exception:
                pass

            cand = Candidate(
                x=0, y=0, rect=rect, source="uia",
                confidence=round(score, 3), label=name,
                control_type=ctype, window=win_name,
            )
            cand = _clamp_to_screen(cand)
            if cand is not None:
                scored.append((score, cand))
        except Exception:
            continue
    return scored


def find_by_uia(description: str,
                root=None,
                min_confidence: float = 0.55,
                max_results: int = 8,
                timeout_s: float = 1.5,
                window: str | None = None) -> list[Candidate]:
    """Layer 0 — ask Windows where the element is.

    Returns candidates best-first. An empty list means the tree could not see it
    (or this is not Windows, or uiautomation is not installed) and the caller
    should fall through to OCR.

    `window` narrows the search to windows whose title contains that string.
    Without it the foreground window is tried first, then every other visible
    top-level window — see `_visible_top_windows` for why that fallback is not
    optional.
    """
    if not _IS_WINDOWS:
        return []
    a = _uia_module()
    if a is None:
        return _pywinauto_find(description, min_confidence, max_results)

    deadline = time.monotonic() + timeout_s
    scored: list[tuple[float, Candidate]] = []

    # An explicit root means the caller knows exactly where to look.
    if root is not None:
        try:
            win_name = str(root.Name or "")
        except Exception:
            win_name = ""
        try:
            nodes = _walk_controls(root, deadline=deadline)
        except Exception:
            return []
        scored = _score_nodes(nodes, description, min_confidence, win_name)
    else:
        windows = _visible_top_windows()
        # Each window gets its OWN slice of the budget, and this is the fix for a
        # reproduced misclick rather than a refinement.
        #
        # The budget used to be one deadline shared by every window in the list.
        # `_visible_top_windows` returns the foreground window first and the
        # shell — the taskbar — last, so a single slow window (Chrome, an
        # Electron app, anything with a deep tree) spent the whole budget and the
        # `break` below fired before the taskbar was ever walked. Taskbar icons
        # are the most-clicked thing a desktop assistant is asked for, so the
        # target was not merely ranked low, it was never searched for at all: the
        # call fell through to OCR, then to the vision model, and clicked a
        # neighbour. Measured on this machine, "WhatsApp icon" resolved to the
        # taskbar button at x=614; with one slow window ahead of the taskbar it
        # resolved to x=546 — the icon immediately to its left — via vision,
        # which is exactly the "it clicks the icon to the left" report.
        #
        # An equal share per window costs nothing in the normal case, because a
        # healthy window is walked in tens of milliseconds and never touches its
        # slice. It only bites when a window is genuinely pathological, and then
        # it bounds that one window instead of starving every window after it.
        per_window = max(0.2, timeout_s / max(1, len(windows)))
        deadline = time.monotonic() + per_window * max(1, len(windows)) + 0.2

        for w in windows:
            if time.monotonic() > deadline:
                break
            try:
                win_name = str(w.Name or "")
            except Exception:
                win_name = ""
            if window and window.lower() not in win_name.lower():
                continue
            try:
                nodes = _walk_controls(
                    w, deadline=min(time.monotonic() + per_window, deadline))
            except Exception:
                continue
            scored += _score_nodes(nodes, description, min_confidence, win_name)
            # Stop as soon as something matches well. Walking every window on
            # the desktop would cost more than the search is worth, and a
            # confident hit in the foreground window is almost always the
            # intended one.
            if scored and max(s for s, _ in scored) >= 0.9:
                break

    scored.sort(key=lambda p: p[0], reverse=True)
    return [c for _, c in scored[:max_results]]


def _pywinauto_find(description: str, min_confidence: float,
                    max_results: int) -> list[Candidate]:
    """Layer 0 fallback when uiautomation is missing.

    pywinauto is already a dependency, so this keeps the fast path alive rather
    than dropping straight to a model call. It is coarser — one flat descendant
    query — but for a button in a standard dialog it is still exact.
    """
    try:
        from pywinauto import Desktop
    except ImportError:
        return []

    try:
        win = Desktop(backend="uia").window(active_only=True)
        if win is None:
            return []
        win_name = ""
        try:
            win_name = str(win.window_text() or "")
        except Exception:
            pass
        scored: list[tuple[float, Candidate]] = []
        deadline = time.monotonic() + 1.5
        for ctrl in win.descendants():
            if time.monotonic() > deadline:
                break
            try:
                info = ctrl.element_info
                name = str(info.name or "")
                if not name.strip():
                    continue
                score = _similarity(description, name)
                if score < min_confidence:
                    continue
                r = info.rectangle
                rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
                cand = Candidate(0, 0, rect, "uia", round(score, 3), name,
                                 str(info.control_type or ""), win_name)
                cand = _clamp_to_screen(cand)
                if cand is not None:
                    scored.append((score, cand))
            except Exception:
                continue
        scored.sort(key=lambda p: p[0], reverse=True)
        return [c for _, c in scored[:max_results]]
    except Exception:
        return []


def uia_available() -> bool:
    return _IS_WINDOWS and (_uia_module() is not None or _pywinauto_available())


def _pywinauto_available() -> bool:
    try:
        import pywinauto  # noqa: F401
        return True
    except ImportError:
        return False


# ── Layer 1: OCR ─────────────────────────────────────────────────────────────

# Two OCR engines, and the choice between them is not close.
#
# The Windows one (Windows.Media.Ocr) is part of the OS, needs no model
# download, and on this machine reads a full 1920x1084 window in **0.095 s**.
# RapidOCR runs the PP-OCRv4 ONNX models on the CPU and takes **7.3 s** for the
# same frame — the detector is ~2 s and recognition of ~50 text runs is the
# other ~5 s, and neither downscaling nor batching moves it much, because the
# cost is per-crop model inference.
#
# 77x is the difference between a layer that can sit in a click path and one
# that cannot, so Windows OCR is the primary engine and RapidOCR is the
# fallback for non-Windows or a system whose OCR language pack is missing.
_ocr_engine = None
_ocr_kind = ""
_ocr_failed = False


def _get_ocr():
    """Build the OCR engine once. Returns ("winocr"|"rapidocr", engine) or None."""
    global _ocr_engine, _ocr_kind, _ocr_failed
    if _ocr_engine is not None or _ocr_failed:
        return (_ocr_kind, _ocr_engine) if _ocr_engine is not None else None

    eng = _build_win_ocr()
    if eng is not None:
        _ocr_engine, _ocr_kind = eng, "winocr"
        print("[Grounding] OCR engine ready (Windows.Media.Ocr)")
        return _ocr_kind, _ocr_engine

    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        _ocr_kind = "rapidocr"
        print("[Grounding] OCR engine ready (RapidOCR — slower fallback)")
        return _ocr_kind, _ocr_engine
    except Exception as e:
        _ocr_failed = True
        print(f"[Grounding] OCR unavailable ({type(e).__name__}: {e})")
        return None


_win_ocr_engine = None
_win_ocr_tried = False


def _build_win_ocr():
    """The Windows OCR engine, or None if the OS cannot provide one.

    Tries the user's own profile languages first, so a non-English install reads
    its own language, then falls back to English. `try_create_from_language`
    returns None (rather than raising) when that language's OCR pack is not
    installed, which is the common case on a fresh Windows.
    """
    global _win_ocr_engine, _win_ocr_tried
    if _win_ocr_tried:
        return _win_ocr_engine
    _win_ocr_tried = True
    if not _IS_WINDOWS:
        return None
    try:
        from winsdk.windows.media.ocr import OcrEngine
    except ImportError:
        return None
    try:
        eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None:
            from winsdk.windows.globalization import Language
            for tag in ("en-US", "en-GB"):
                eng = OcrEngine.try_create_from_language(Language(tag))
                if eng is not None:
                    break
        _win_ocr_engine = eng
    except Exception:
        _win_ocr_engine = None
    return _win_ocr_engine


def _win_ocr_words(img, origin: tuple[int, int], inv: float):
    """Run Windows OCR and return [(text, physical_rect)] for every line.

    Lines rather than words: a control's label is usually a whole line, and
    matching a description against "Save as" beats matching it against "Save".
    Word boxes are still used to build the line's rectangle, which is what makes
    the reported centre land on the middle of the text rather than its start.

    `inv` scales the engine's coordinates back to physical pixels — the engine
    sees whatever size the capture was, which may be downscaled.
    """
    import asyncio

    from winsdk.windows.globalization import Language  # noqa: F401
    from winsdk.windows.graphics.imaging import (
        BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap,
    )
    from winsdk.windows.security.cryptography import CryptographicBuffer

    eng = _build_win_ocr()
    if eng is None:
        return []

    import numpy as np
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return []
    # The engine wants BGRA8. Building it with numpy and handing over one buffer
    # avoids a per-pixel Python loop, which on a 1080p frame would cost more
    # than the recognition itself.
    bgra = np.empty((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    bgra[:, :, 0] = arr[:, :, 2]
    bgra[:, :, 1] = arr[:, :, 1]
    bgra[:, :, 2] = arr[:, :, 0]
    bgra[:, :, 3] = 255
    bgra = np.ascontiguousarray(bgra)

    buf = CryptographicBuffer.create_from_byte_array(bgra.tobytes())
    sb = SoftwareBitmap.create_copy_from_buffer(
        buf, BitmapPixelFormat.BGRA8, arr.shape[1], arr.shape[0],
        BitmapAlphaMode.PREMULTIPLIED)

    async def _run():
        return await eng.recognize_async(sb)

    # The API is async-only, and this is called from a worker thread that is not
    # running a loop, so asyncio.run is safe here.
    try:
        result = asyncio.run(_run())
    except RuntimeError:
        # Already inside a loop (called from async context): run it on a
        # throwaway thread rather than failing the search.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            result = ex.submit(lambda: asyncio.run(_run())).result(timeout=10)

    ox, oy = origin
    out: list[tuple[str, tuple[int, int, int, int]]] = []
    for line in result.lines:
        text = str(line.text or "")
        if not text.strip():
            continue
        xs: list[float] = []
        ys: list[float] = []
        for w in line.words:
            r = w.bounding_rect
            xs += [r.x, r.x + r.width]
            ys += [r.y, r.y + r.height]
        if not xs:
            continue
        rect = (round(min(xs) * inv) + ox, round(min(ys) * inv) + oy,
                round(max(xs) * inv) + ox, round(max(ys) * inv) + oy)
        out.append((text, rect))
    return out


def _rapid_ocr_lines(img, origin: tuple[int, int], inv: float):
    """RapidOCR's equivalent of `_win_ocr_words`: [(text, physical_rect)]."""
    kind_engine = _get_ocr()
    if kind_engine is None:
        return []
    _, engine = kind_engine
    try:
        import numpy as np
        result, _ = engine(np.asarray(img))
    except Exception as e:
        print(f"[Grounding] OCR run failed: {e}")
        return []
    if not result:
        return []
    ox, oy = origin
    out: list[tuple[str, tuple[int, int, int, int]]] = []
    for entry in result:
        try:
            box, text = entry[0], str(entry[1])
            xs = [float(p[0]) * inv for p in box]
            ys = [float(p[1]) * inv for p in box]
            rect = (round(min(xs)) + ox, round(min(ys)) + oy,
                    round(max(xs)) + ox, round(max(ys)) + oy)
            out.append((text, rect))
        except Exception:
            continue
    return out


def ocr_available() -> bool:
    if _IS_WINDOWS and _build_win_ocr() is not None:
        return True
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def find_by_ocr(description: str,
                region: tuple[int, int, int, int] | None = None,
                min_confidence: float = 0.6,
                max_results: int = 8,
                max_px: int = 1920) -> list[Candidate]:
    """Layer 1 — find the description as visible TEXT on screen.

    This is what covers the apps the accessibility tree cannot see: Electron,
    Chrome, games, remote desktops, anything drawn to a canvas. It reads the
    actual pixels, so it finds what the user can see rather than what the app
    admits to exposing.

    `region` limits the search to a physical rect, and it is worth passing: on a
    full 1080p screen a detection pass takes several seconds, while scoped to one
    window it is a fraction of that and cannot match a word in an unrelated
    window behind the target. When no region is given this falls back to the
    foreground window's own rectangle, then to the whole primary display.

    `max_px` caps the longest side of what is fed to the detector. Text has to
    stay legible, so this is generous compared to the vision path — but a 4K
    frame costs several times a 1080p one for no gain in which words are found.
    Coordinates are scaled back up afterwards, so a caller always gets physical
    screen pixels regardless of what size the detector actually saw.
    """
    if not ocr_available():
        return []

    if region is None:
        fg = foreground_window()
        if fg is not None:
            region = fg[1]

    try:
        img, origin = sg.capture(region=region, with_cursor=False, max_px=max_px)
    except Exception as e:
        print(f"[Grounding] OCR capture failed: {e}")
        return []

    # How much the capture was shrunk. OCR coordinates come back in the scaled
    # image, so they have to be divided by this before the origin is added —
    # otherwise a region-limited, downscaled search returns coordinates that are
    # correct only at 100% scaling with no resize, which is precisely the
    # assumption that made the old finder unreliable.
    if region is not None:
        scale = img.width / max(1, region[2])
    else:
        vd = sg.virtual_desktop()
        scale = img.width / max(1, vd.width)
    inv = 1.0 / scale if scale else 1.0

    kind_engine = _get_ocr()
    if kind_engine is None:
        return []
    kind, _ = kind_engine
    if kind == "winocr":
        lines = _win_ocr_words(img, origin, inv)
    else:
        lines = _rapid_ocr_lines(img, origin, inv)

    if not lines:
        return []

    scored: list[tuple[float, Candidate]] = []
    for text, rect in lines:
        score = _similarity(description, text)
        if score < min_confidence:
            continue
        cand = Candidate(0, 0, rect, "ocr", round(score, 3), text)
        cand = _clamp_to_screen(cand)
        if cand is not None:
            scored.append((score, cand))

    scored.sort(key=lambda p: p[0], reverse=True)
    return [c for _, c in scored[:max_results]]


# ── Layer 2: vision grounding ────────────────────────────────────────────────

def _vision_call(image_bytes: bytes, prompt: str, tier: str, timeout_ms: int):
    """One vision generation through the shared Gemini wrapper.

    Kept in one place so the model choice and the timeout are not scattered.
    `gemini.call` walks a fallback ladder, which matters here: a grounding
    request that lands on a Live *audio* model comes back as a transcript rather
    than JSON, so the caller validates the text instead of trusting it.
    """
    try:
        from google.genai import types as gtypes
        from core import gemini
        return gemini.call(
            [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
            tier=tier, timeout_ms=timeout_ms,
        )
    except Exception as e:
        print(f"[Grounding] vision call failed: {e}")
        return None


_BOX_RE = re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,"
                     r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")


def parse_box(text: str, frame_w: int, frame_h: int,
              origin: tuple[int, int] = (0, 0)) -> tuple[int, int, int, int] | None:
    """Turn a model's box answer into a physical pixel rect — or None.

    This is the function whose absence caused most of the misclicks. The old
    code assumed every answer was normalised 0-1000 and applied that scale
    unconditionally, so a model that answered in pixels, or in 0-1 fractions,
    produced a coordinate that looked plausible and was simply wrong.

    The unit is inferred from the numbers themselves:

        all values <= 1.0 and at least one fractional  -> 0-1 fractions
        all values <= 1000                             -> 0-1000 normalised
        anything larger                                -> pixels of this frame

    Returns None for anything unusable — a degenerate box, a box that does not
    overlap the frame, or an ambiguous answer — so the caller retries or falls
    back instead of clicking at a guess.
    """
    m = _BOX_RE.search(text or "")
    if not m:
        return None
    try:
        a, b, c, d = (float(g) for g in m.groups())
    except (TypeError, ValueError):
        return None

    vals = (a, b, c, d)
    # A negative value is not a valid box in ANY convention: the model is looking
    # at a captured image whose origin is its top-left corner, so nothing in it
    # can be left of or above zero. Seeing one means the answer is malformed.
    if min(vals) < 0:
        return None
    mx = max(vals)

    # Model output order is [ymin, xmin, ymax, xmax] — y first, unlike almost
    # every other convention.
    def as_yxyx(v):
        ymin, xmin, ymax, xmax = v
        l, t = round(xmin), round(ymin)
        r, b = round(xmax), round(ymax)
        return l, t, r, b

    def scaled(v, sw, sh):
        ymin, xmin, ymax, xmax = v
        return (round(xmin * sw), round(ymin * sh),
                round(xmax * sw), round(ymax * sh))

    # Readings in order of trust. Normalised 0-1000 is what the prompt asks for,
    # so it is tried first; pixels is the unprompted fallback.
    #
    # The 0-1 reading is only considered when at least one value actually has a
    # decimal point. A model answering normalised will happily return 0 or 1 for
    # a box pinned to an edge, and reading that as "fraction" would collapse the
    # box to the top-left pixel.
    readings: list[tuple[int, int, int, int]] = []
    if mx <= 1.0 and _has_fraction(text, m):
        readings.append(scaled(vals, frame_w, frame_h))
    if mx <= 1000.0:
        readings.append(scaled(vals, frame_w / 1000.0, frame_h / 1000.0))
    readings.append(as_yxyx(vals))

    ox, oy = origin
    for l, t, r, b in readings:
        if r < l:
            l, r = r, l
        if b < t:
            t, b = b, t
        w, h = r - l, b - t
        # Reject degenerate or absurd boxes rather than clamping them into a
        # confident-looking wrong answer.
        if w < 2 or h < 2:
            continue
        if w > frame_w * 1.05 or h > frame_h * 1.05:
            continue
        # The box has to sit at least partly inside the frame.
        if r < 0 or b < 0 or l > frame_w or t > frame_h:
            continue
        # A box covering essentially the whole frame is not a located element.
        if (w * h) / max(1, frame_w * frame_h) > 0.92:
            continue
        return (l + ox, t + oy, r + ox, b + oy)

    return None


def _has_fraction(text: str, m: re.Match) -> bool:
    return any("." in g for g in m.groups())


def find_by_vision(description: str,
                   region: tuple[int, int, int, int] | None = None,
                   tier: str = "gemini-2.5-flash",
                   timeout_ms: int = 20_000,
                   coarse_to_fine: bool = True,
                   max_px: int = 1600) -> list[Candidate]:
    """Layer 2 — ask a vision model, and check its answer.

    Two passes when `coarse_to_fine`: a cheap look at the whole frame to find the
    rough area, then a second look at a crop of that area at native resolution.
    The second pass is what recovers accuracy — a button that is 12 px wide in a
    downscaled 1600 px frame is 40 px wide in a crop of its own neighbourhood,
    and the model localises it far better at that size. The two boxes are
    compared, and agreement raises confidence.

    Coordinates are always reported in physical screen pixels, whatever frame
    the model actually saw, because `parse_box` is told the frame size and the
    origin it has to map back through.
    """
    def _one(reg, mp) -> tuple[tuple[int, int, int, int] | None, int, int]:
        try:
            jpeg, origin, (fw, fh) = sg.capture_jpeg(
                region=reg, with_cursor=True, max_px=mp, quality=85)
        except Exception as e:
            print(f"[Grounding] vision capture failed: {e}")
            return None, 0, 0
        prompt = (
            f"Locate the UI element described as: '{description}'. "
            "Reply with ONLY a JSON object: {\"box_2d\": [ymin, xmin, ymax, xmax]} "
            "with coordinates normalized to 0-1000 "
            "(0,0 = top-left of the image, 1000,1000 = bottom-right). "
            "If the element is not visible, reply exactly: NOT_FOUND"
        )
        resp = _vision_call(jpeg, prompt, tier, timeout_ms)
        if resp is None:
            return None, fw, fh
        text = (getattr(resp, "text", "") or "").strip()
        if "NOT_FOUND" in text.upper():
            return None, fw, fh
        box = parse_box(text, fw, fh, origin)
        return box, fw, fh

    box, fw, fh = _one(region, max_px)
    if box is None:
        return []

    # A single look is NOT trusted, and this is a correction rather than a
    # refinement.
    #
    # The confirmation pass below used to be skipped whenever the caller had
    # already supplied a `region` (`and region is None`), on the reasoning that a
    # narrowed search is easier. It is — but that is exactly when a one-look
    # answer was being trusted blindly, and the region path is the one a misclick
    # complaint actually travels. Reproduced against a WhatsApp chat list: asked
    # for a contact row with the window passed as a region, the layer returned
    # one candidate at conf 0.60 — the row ABOVE the one asked for. With the
    # confirmation pass restored it agrees with itself and reports 0.90; when it
    # does not agree, both boxes come back so the caller's retry loop has
    # somewhere to go.
    #
    # Unconfirmed answers also no longer claim 0.6. A number that cannot tell a
    # confirmed hit from a guess is worse than no number, because every caller
    # below compares against it.
    conf = 0.45
    alt: tuple[int, int, int, int] | None = None
    if coarse_to_fine:
        # Second pass: re-ask about a padded crop of the first answer, at full
        # resolution. The padding matters — if the first box was slightly off,
        # an unpadded crop would cut the element out of its own zoom.
        l, t, r, b = box
        pad_x = max(40, int((r - l) * 0.6))
        pad_y = max(40, int((b - t) * 0.6))
        crop = (max(0, l - pad_x), max(0, t - pad_y),
                (r - l) + 2 * pad_x, (b - t) + 2 * pad_y)
        box2, _, _ = _one(crop, None)
        if box2 is not None:
            # Did the refined box land inside (or very near) the coarse one?
            l2, t2, r2, b2 = box2
            cx2, cy2 = (l2 + r2) / 2, (t2 + b2) / 2
            inside = (l - pad_x <= cx2 <= r + pad_x) and (t - pad_y <= cy2 <= b + pad_y)
            if inside:
                # Agreement between two independent looks is the strongest
                # signal this layer can produce.
                conf = 0.9
                box = box2
            else:
                # They disagree: the crop pass found something else entirely.
                # Both are returned, coarse first, so a caller that clicks, sees
                # nothing change and retries has the other reading to try —
                # rather than clicking a point only one of the two passes
                # believes in and then giving up.
                conf = 0.4
                alt = box2

    cand = Candidate(0, 0, box, "vision", conf, description)
    cand = _clamp_to_screen(cand)
    out = [cand] if cand is not None else []
    if alt is not None:
        other = Candidate(0, 0, alt, "vision", 0.35, description)
        other = _clamp_to_screen(other)
        if other is not None:
            out.append(other)
    return out


# ── The ladder ───────────────────────────────────────────────────────────────

def resolve(description: str,
            window: str | None = None,
            layers: Sequence[str] = ("uia", "ocr", "vision"),
            region: tuple[int, int, int, int] | None = None,
            allow_vision: bool = True,
            min_confidence: float = 0.55) -> list[Candidate]:
    """Find an element by description, trying the cheapest layer that can see it.

    Returns every candidate the winning layer produced, best first — not just
    the top one. A caller that wants to click the first can; a caller that wants
    to try, verify, and fall through to the second has the options to do that,
    which is what makes the verify-retry loop in `computer_control` possible.

    An empty list means nothing found it, and the caller should say so rather
    than click somewhere arbitrary.

    `window` narrows the search to a window whose title contains that string —
    worth passing whenever it is known, because it stops a generic description
    ("Save") from matching the same word in an unrelated window behind it.
    """
    if not description or not description.strip():
        return []

    if region is None and window:
        region = region_for_window(window)
        # A window that could not be located is not a reason to give up; the
        # full-screen search is just less precise.

    for layer in layers:
        try:
            if layer == "uia":
                hits = find_by_uia(description, min_confidence=min_confidence,
                                   window=window)
            elif layer == "ocr":
                # OCR scopes itself to the foreground window when it is not
                # handed a region, which is both much faster than a full screen
                # pass and far less likely to match a word in another window.
                hits = find_by_ocr(description, region=region,
                                   min_confidence=max(0.6, min_confidence))
            elif layer == "vision":
                if not allow_vision:
                    continue
                hits = find_by_vision(description, region=region)
            else:
                continue
        except Exception as e:
            print(f"[Grounding] layer {layer} failed: {type(e).__name__}: {e}")
            continue

        if hits:
            print(f"[Grounding] '{description}' -> {hits[0]} "
                  f"({len(hits)} candidate{'s' if len(hits) != 1 else ''})")
            return hits

    print(f"[Grounding] '{description}' NOT FOUND by any layer")
    return []


def resolve_one(description: str, **kwargs) -> Candidate | None:
    """The single best candidate, or None."""
    hits = resolve(description, **kwargs)
    return hits[0] if hits else None


# ── Windows ──────────────────────────────────────────────────────────────────

def region_for_window(title_fragment: str) -> tuple[int, int, int, int] | None:
    """The physical rectangle of the first visible window whose title matches.

    Used to scope a search — to OCR one app rather than the whole desktop, and
    to tell the model which window it is looking at. Returns None when nothing
    matches, which callers treat as "search everywhere" rather than an error.
    """
    if not title_fragment:
        return None
    if not _IS_WINDOWS:
        return None

    a = _uia_module()
    if a is not None:
        try:
            root = a.GetRootControl()
            for w in root.GetChildren():
                try:
                    if str(w.ControlTypeName) != "WindowControl":
                        continue
                    name = str(w.Name or "")
                    if title_fragment.lower() not in name.lower():
                        continue
                    if w.IsOffscreen:
                        continue
                    br = w.BoundingRectangle
                    if br is None:
                        continue
                    rect = (int(br.left), int(br.top), int(br.right), int(br.bottom))
                    if rect[2] - rect[0] < 50 or rect[3] - rect[1] < 50:
                        continue
                    return rect
                except Exception:
                    continue
        except Exception:
            pass

    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            try:
                if title_fragment.lower() in (w.title or "").lower() and w.visible:
                    if w.width >= 50 and w.height >= 50:
                        return (int(w.left), int(w.top),
                                int(w.left + w.width), int(w.top + w.height))
            except Exception:
                continue
    except Exception:
        pass
    return None


def force_foreground(hwnd: int) -> bool:
    """Make a window the real foreground window, and say whether it worked.

    `QWidget.activateWindow()` only *asks*. Windows refuses the request when a
    window from another process holds the foreground, and Qt reports the widget
    as active anyway — so a caller believes its window is focused while every
    keystroke and click goes somewhere else. That mismatch is what made a
    click-verification run report "the button did not register" while the
    cursor was demonstrably sitting on the button.

    The documented way around the refusal is the AttachThreadInput trick: a
    process may only change the foreground window if it is itself the
    foreground process, so this briefly attaches this thread's input queue to
    the current foreground window's thread, which makes the call legal, then
    detaches.
    """
    if not _IS_WINDOWS or not hwnd:
        return False
    u = ctypes.windll.user32
    try:
        if u.GetForegroundWindow() == hwnd:
            return True
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)  # SW_RESTORE

        fg = u.GetForegroundWindow()
        target_thread = u.GetWindowThreadProcessId(hwnd, None)
        this_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        other_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0

        attached = False
        if other_thread and other_thread != this_thread:
            attached = bool(u.AttachThreadInput(other_thread, this_thread, True))
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(other_thread, this_thread, False)

        return u.GetForegroundWindow() == hwnd
    except Exception:
        return False


def foreground_window() -> tuple[str, tuple[int, int, int, int]] | None:
    """(title, physical rect) of the window the user is looking at."""
    if not _IS_WINDOWS:
        return None
    a = _uia_module()
    if a is not None:
        try:
            fg = _foreground_window_uia()
            if fg is not None:
                br = fg.BoundingRectangle
                rect = (int(br.left), int(br.top), int(br.right), int(br.bottom))
                return str(fg.Name or ""), rect
        except Exception:
            pass
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        if w is not None:
            return (w.title or "", (int(w.left), int(w.top),
                                    int(w.left + w.width), int(w.top + w.height)))
    except Exception:
        pass
    return None


def describe_layers() -> str:
    """Which layers are usable right now — the first thing to check when a
    click starts going through the slow path."""
    parts = []
    parts.append(f"uia={'yes' if uia_available() else 'NO'}")
    parts.append(f"ocr={'yes' if ocr_available() else 'NO'}")
    parts.append("vision=yes")
    return " ".join(parts)
