"""
core/ui_readability.py — make the HUD easy to read without redesigning it.

WHY
    Almost all text in ui.py was drawn in Courier New at 6-8 pt (99 of 117 font
    declarations), in saturated cyan/blue on a near-black teal background. Thin
    monospace at that size is hard to read on its own; bright blue-on-black adds
    colour fringing and eye strain on top.

WHAT THIS DOES (all of it can be switched off, see the end)
    1. Fonts      Courier New  ->  the system UI font (Segoe UI on Windows), and the
                  smallest sizes are raised. Courier New is ~20% wider than Segoe UI
                  at the same size, so +1..2 pt keeps the layouts the same width.
    2. Text colour  Any text that was the accent blue is drawn in a soft off-white
                  instead. The accent colour stays on borders, buttons, the HUD
                  rings and the waveform; only the LETTERS change.
    3. App-wide default font, so dialogs/tooltips match.

HOW (no edits needed in the 117 call sites)
    * `QFont` here is a thin subclass that remaps "Courier New" when ui.py creates a font.
    * QWidget.setStyleSheet is wrapped: `color: <accent>` becomes a neutral light colour.
      (`border-color`, `background`, `selection-color` etc. are not touched.)
    * QPainter.drawText is wrapped the same way for text painted by hand (HUD, bars).

SWITCH OFF:  "ui_readable": false   in config/api_keys.json   (then restart)
"""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path

from PyQt6.QtGui import QColor, QFont as _QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QFrame, QWidget

_OS = platform.system()
BASE_DIR = Path(__file__).resolve().parents[1]

UI_FONT   = {"Windows": "Cascadia Code", "Darwin": "SF Mono"}.get(_OS, "DejaVu Sans Mono")
MONO_FONT = {"Windows": "Consolas", "Darwin": "Menlo"}.get(_OS, "DejaVu Sans Mono")

# Neutral text colours (contrast against the #10161d panel: 14.5 / 9.6 / 6.3 : 1).
TEXT_PRIMARY   = "#e6edf3"
TEXT_SECONDARY = "#b6c2cd"
TEXT_MUTED     = "#8b98a6"

# Old text colours that may still be written literally somewhere, and what they become.
_LEGACY = {
    "#8ffcff": TEXT_PRIMARY, "#d8f8ff": TEXT_PRIMARY,
    "#5ab8cc": TEXT_SECONDARY,
    "#3a8a9a": TEXT_MUTED,
    "#00d4ff": TEXT_PRIMARY, "#007a99": TEXT_SECONDARY,
}

# Raise the tiniest sizes. (Courier New 8 pt  ->  UI font 10 pt, and so on.)
_SIZE_MAP = {5: 9, 6: 9, 7: 9, 8: 10, 9: 10, 10: 11}


def enabled() -> bool:
    try:
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return bool(json.load(f).get("ui_readable", True))
    except Exception:
        return True


_ON = enabled()
_accent_getter = lambda: ()          # replaced by install(); returns (PRI, PRI_DIM)


# ── 1. fonts ────────────────────────────────────────────────────────────────
class QFont(_QFont):
    """Drop-in QFont: "Courier New" is swapped for a readable font."""

    def __init__(self, *args):
        if _ON and args and isinstance(args[0], str) and args[0].lower() == "courier new":
            args = list(args)
            size = args[1] if len(args) > 1 and isinstance(args[1], int) else None
            args[0] = UI_FONT
            if size in _SIZE_MAP:
                args[1] = _SIZE_MAP[size]
        super().__init__(*args)


def apply_app_font(app: QApplication) -> None:
    if _ON and app is not None:
        f = _QFont(UI_FONT, 10)
        f.setStyleStrategy(_QFont.StyleStrategy.PreferAntialias)
        app.setFont(f)


# ── 2. colours ──────────────────────────────────────────────────────────────
def _neutral_for(hex6: str) -> str | None:
    """Neutral replacement if `hex6` is one of the blue text colours, else None."""
    h = hex6.lower()
    try:
        vals = [str(v).lower() for v in _accent_getter()]
    except Exception:
        vals = []
    if vals and h == vals[0]:
        return TEXT_PRIMARY                      # accent used as text
    if len(vals) > 1 and h == vals[1]:
        return TEXT_SECONDARY                    # dim accent used as text
    if h in vals[2:]:
        return TEXT_MUTED                        # border colours used as text: ~1.4:1, unreadable
    return _LEGACY.get(h)


_COLOR_RE = re.compile(r"(?<![-\w])(color\s*:\s*)(#[0-9a-fA-F]{6})\b")


def readable_stylesheet(ss: str) -> str:
    if not ss or "color" not in ss:
        return ss
    return _COLOR_RE.sub(lambda m: m.group(1) + (_neutral_for(m.group(2)) or m.group(2)), ss)


_installed = False
_orig_set_ss = QWidget.setStyleSheet
_orig_draw_text = QPainter.drawText


def _set_stylesheet(self, ss):
    try:
        # Divider lines are QFrames whose `color` IS the line colour, not text.
        is_rule = isinstance(self, QFrame) and self.frameShape() in (
            QFrame.Shape.HLine, QFrame.Shape.VLine)
        if not is_rule:
            ss = readable_stylesheet(ss)
    except Exception:
        pass
    return _orig_set_ss(self, ss)


def _draw_text(self, *args):
    new = None
    try:
        pen = self.pen()
        n = _neutral_for(pen.color().name())
        if n:
            new = QColor(n)
            new.setAlpha(pen.color().alpha())
    except Exception:
        new = None
    if new is None:
        return _orig_draw_text(self, *args)
    saved = QPen(pen)
    tmp = QPen(pen)
    tmp.setColor(new)
    self.setPen(tmp)
    try:
        return _orig_draw_text(self, *args)
    finally:
        self.setPen(saved)


def install(accent_getter) -> None:
    """Call once, after the palette exists. accent_getter() -> (PRI, PRI_DIM, BORDER, BORDER_B, BORDER_A)."""
    global _installed, _accent_getter
    _accent_getter = accent_getter
    if _installed or not _ON:
        return
    QWidget.setStyleSheet = _set_stylesheet          # type: ignore[method-assign]
    QPainter.drawText = _draw_text                   # type: ignore[method-assign]
    _installed = True
