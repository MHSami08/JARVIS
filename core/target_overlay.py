"""The targeting reticle — what JARVIS is about to click, drawn on screen.

A frameless, always-on-top, click-through window that outlines the element a
targeting layer found, marks its centre with a crosshair, and names the source
that found it. It exists for one reason: an assistant that moves your mouse
should show you where before it does, so a wrong target is something you see
coming rather than something you find out about afterwards.

Four things about this window are load-bearing, and each was measured rather
than assumed.

**It is a separate top-level window, not a child of the HUD.** Every other
overlay in this app is a child of `centralWidget()` positioned relative to the
HUD. This one draws at *screen* coordinates, so it cannot be. It is the first
top-level overlay in the codebase.

**It must convert physical pixels to Qt logical pixels.** Targeting layers
report physical coordinates; `setGeometry` takes logical ones. On this machine
they are identical (100% scaling), which is exactly why the conversion is easy
to leave out and then have the reticle draw half a screen away on a scaled
display. `screen_geometry.logical_rect` is the only place that conversion
happens.

**It must be click-through.** `WindowTransparentForInput` sets `WS_EX_TRANSPARENT`
so the window is never the target of a click — verified by clicking a point the
overlay fully covers and watching the click reach the window underneath. Adding
`WindowDoesNotAcceptFocus` sets `WS_EX_NOACTIVATE`, so it cannot steal focus from
the app being driven. Note that `WA_ShowWithoutActivating` alone does *not*
produce `WS_EX_NOACTIVATE`; the flag is required.

**It is captured by screenshots, and cannot be excluded.** `WS_EX_LAYERED` (which
translucency forces on) makes `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`
fail, so a capture taken while the reticle is up contains the reticle. Any code
that screenshots in order to decide something must call `hide()` first — see
`screen_geometry`'s callers, and `screen_agent`'s observe step. The corner
brackets and the out-of-rect label also keep the drawn area off the element
itself, so even a capture that catches it is not looking through red paint.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import screen_geometry as sg

# Colours deliberately chosen from outside the palette in ui.C.
#
# core/ui_readability.py monkeypatches QPainter.drawText process-wide and swaps
# any pen whose colour matches the accent palette (C.PRI, C.PRI_DIM, C.BORDER*)
# for a neutral grey — so hand-painted text in the accent colour would silently
# lose its colour. These two are not in that table and survive untouched.
# drawLine/drawRect are not patched at all, so the reticle itself is unaffected
# either way.
_TARGET_COLOR = "#ff3b30"   # the element box and crosshair
_AGENT_COLOR = "#ff6b00"    # C.ACC — the AUTONOMOUS badge
_DIM_COLOR = "#ffd0cc"      # the label

# Room above the box for the text drawn over it. Segoe UI 10 Bold has an ascent
# of 14 px, so too small a pad clips the glyphs entirely — they are drawn above
# the window's own top edge and simply do not appear.
#
# Two lines are allowed for because the detail line sits above the label, and
# reserving room for one would silently crop the other. `_top_pad` picks the
# right amount rather than always reserving both, so a target with no detail
# line does not float an empty band above it.
_PAD_TOP_ONE = 22
_PAD_TOP_TWO = 36
_PAD_SIDE = 10


def _top_pad(label: str, detail: str) -> int:
    return _PAD_TOP_TWO if (label and detail) else _PAD_TOP_ONE

# How long a target stays up when the caller does not say. Long enough to notice
# mid-flow, short enough that a stray one does not linger over the desktop.
DEFAULT_DWELL_MS = 1400


class TargetOverlay(QWidget):
    """Draws the current target. One instance, reused for every click.

    Create it on the Qt main thread. All methods are meant to be called from
    that thread — worker threads reach it through `JarvisUI.show_target`, which
    marshals across with a signal.
    """

    # Emitted after a target has actually been painted, so a caller can wait for
    # the reticle to be on screen before it clicks. The first paint of a newly
    # shown window costs ~18 ms; a subsequent geometry update is under a
    # millisecond. Without this, a click can land before the user sees anything.
    painted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput     # WS_EX_TRANSPARENT
            | Qt.WindowType.WindowDoesNotAcceptFocus      # WS_EX_NOACTIVATE
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._rect = QRect()
        self._label = ""
        self._badge = ""
        self._detail = ""
        self._shown = False

        self._label_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self._badge_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self._detail_font = QFont("Segoe UI", 8)

        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self.clear_target)

    # ── public API ───────────────────────────────────────────────────────────

    def show_target(self,
                    physical_rect: tuple[int, int, int, int] | None = None,
                    label: str = "",
                    badge: str = "",
                    detail: str = "",
                    point: tuple[int, int] | None = None,
                    dwell_ms: int | None = DEFAULT_DWELL_MS) -> None:
        """Draw a target.

        `physical_rect` is a physical (left, top, right, bottom) box — what a
        `ui_grounding.Candidate` carries. `point` is a physical (x, y) for a
        target with no box, such as a cursor position or a keyboard-only action;
        a small box is synthesised around it so the reticle still has something
        to point at.

        `badge` is the short status shown on the right, e.g. "AUTONOMOUS", and
        `detail` the small line under the label, e.g. "via uia · 12 ms" — both
        exist so a run that has quietly fallen back to the slow vision layer is
        visible on screen instead of only in a log.
        """
        if physical_rect is None and point is None:
            return
        if physical_rect is None:
            x, y = point  # type: ignore[misc]
            physical_rect = (x - 14, y - 14, x + 14, y + 14)

        l, t, r, b = (int(v) for v in physical_rect)
        if r < l:
            l, r = r, l
        if b < t:
            t, b = b, t
        # A degenerate box has nothing to draw inside, so give it a minimum the
        # eye can find — a 1-px target is a real result (a caret, a thin
        # divider) but an invisible one.
        if r - l < 12:
            cx = (l + r) // 2
            l, r = cx - 6, cx + 6
        if b - t < 12:
            cy = (t + b) // 2
            t, b = cy - 6, cy + 6

        # Physical -> logical, the one conversion that matters. Everything below
        # this line is Qt's coordinate space.
        lx, ly, lw, lh = sg.logical_rect((l, t, r, b))
        self._rect = QRect(lx, ly, lw, lh)
        self._label = str(label or "")[:90]
        self._badge = str(badge or "")[:16]
        self._detail = str(detail or "")[:60]

        # The window has to cover the box plus the label above it and a little
        # room on the right for the badge.
        fm_label = QFontMetrics(self._label_font)
        fm_detail = QFontMetrics(self._detail_font)
        text_w = max(fm_label.horizontalAdvance(self._label),
                     fm_detail.horizontalAdvance(self._detail))
        w = max(lw, text_w + _PAD_SIDE * 2, 80)
        geom = QRect(lx, ly, w, lh).adjusted(
            -_PAD_SIDE, -_top_pad(self._label, self._detail), _PAD_SIDE, 8)
        self.setGeometry(geom)

        if not self._shown:
            self.show()
            self._shown = True
        # update(), not repaint(): let Qt coalesce, and do not paint inside a
        # caller's critical section.
        self.update()

        self._dwell.stop()
        if dwell_ms:
            self._dwell.start(int(dwell_ms))

    def clear_target(self) -> None:
        """Take the reticle down. Cheap, and safe to call when it is not up."""
        self._dwell.stop()
        if self._shown:
            self._shown = False
            self.hide()

    # Qt's own name for it, so a stray close() also clears our state.
    def closeEvent(self, e) -> None:  # noqa: N802
        self._dwell.stop()
        self._shown = False
        super().closeEvent(e)

    def is_target_visible(self) -> bool:
        return self._shown

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _e) -> None:  # noqa: N802
        if not self._shown or self._rect.isNull():
            return

        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # The box is in screen coordinates; the widget is a window sitting
            # over that spot, so translate into the widget's own space.
            r = self._rect.translated(-self.x(), -self.y())

            pen = QPen(QColor(_TARGET_COLOR), 2)
            p.setPen(pen)

            # Corner brackets rather than a full outline: they read as a
            # targeting reticle, and they leave the middle of the element
            # unobscured so a capture taken while the reticle is up is not
            # looking through a rectangle of red over the very thing being
            # examined.
            arm = max(8, min(22, min(r.width(), r.height()) // 3))
            l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
            for (x1, y1, x2, y2) in (
                (l, t, l + arm, t), (l, t, l, t + arm),          # top-left
                (rr, t, rr - arm, t), (rr, t, rr, t + arm),      # top-right
                (l, b, l + arm, b), (l, b, l, b - arm),          # bottom-left
                (rr, b, rr - arm, b), (rr, b, rr, b - arm),      # bottom-right
            ):
                p.drawLine(x1, y1, x2, y2)

            # Crosshair at the exact point that will be clicked — not the box
            # centre, because the caller may have chosen an off-centre point and
            # this is the pixel the mouse will actually visit.
            cx, cy = r.center().x(), r.center().y()
            p.drawLine(cx - 11, cy, cx - 3, cy)
            p.drawLine(cx + 3, cy, cx + 11, cy)
            p.drawLine(cx, cy - 11, cx, cy - 3)
            p.drawLine(cx, cy + 3, cx, cy + 11)
            p.drawEllipse(r.center(), 2, 2)

            # Label above the box, in a colour the readability patch leaves
            # alone.
            base_y = r.top() - 6
            p.setFont(self._label_font)
            p.setPen(QPen(QColor(_DIM_COLOR)))
            if self._label:
                p.drawText(r.left(), base_y, self._label)
            if self._detail:
                p.setFont(self._detail_font)
                fm = QFontMetrics(self._detail_font)
                p.drawText(r.left(), base_y - fm.height() - 1, self._detail)

            if self._badge:
                p.setFont(self._badge_font)
                p.setPen(QPen(QColor(_AGENT_COLOR)))
                fm = QFontMetrics(self._badge_font)
                bw = fm.horizontalAdvance(self._badge)
                p.drawText(r.right() - bw, base_y, self._badge)
        finally:
            p.end()

        # Tell a waiting caller the reticle is on screen. Emitted from
        # paintEvent, which is the only place that knows it truly is.
        self.painted.emit()
