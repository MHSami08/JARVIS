"""One source of truth for screen coordinates.

Every part of JARVIS that needs to know where a pixel is asks this module:
the vision capture, the element finder, the clicker, the targeting overlay and
the calibration tool. Before this existed the conversion was open-coded in three
places (`computer_control._screen_find`, `screen_processor._capture_screen`,
`game_updater`) and they disagreed — different capture sizes, different
assumptions about which monitor, and no DPI handling at all.

Three things are worth knowing before reading the code.

**DPI awareness must be declared before anything else runs.** Windows defaults a
process to DPI-*unaware*, which means the OS lies to it: a 1920x1080 display at
150% scaling reports itself as 1280x720 and every screenshot comes back blurry
and upscaled. The mode can also be changed under us — `mss` asks for
PerMonitor-v2 on its first grab, `pyautogui`/`pyscreeze` ask for the older
v1 at import, and Qt asks for v1 when `QApplication` is built. Whichever wins
last is what the process gets, so a cached screen size from before the switch is
wrong. `ensure_dpi_awareness()` pins it once, early, at PerMonitor-v2.

**Coordinates here are PHYSICAL pixels**, measured from the top-left of the
*primary* monitor. The virtual desktop can extend to negative x (a monitor to
the left of the primary) or negative y (a monitor above it), and `mss` reports
those as negative origins. Physical pixels are what `SetCursorPos`, `mss` and
the accessibility tree all agree on.

**Qt works in LOGICAL pixels.** At 150% scaling a 1920x1080 screen is a
1280x720 `QScreen`. A top-level window positioned with `setGeometry` needs the
logical value, which is why `to_logical` exists — it is the only place that
conversion happens, and getting it wrong draws the targeting overlay in the
wrong place on exactly the display setup this was written for.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass

try:
    import mss as _mss
except ImportError:  # pragma: no cover - mss is a hard requirement
    _mss = None

try:
    from PIL import Image, ImageDraw
    _PIL = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    _PIL = False

_IS_WINDOWS = sys.platform == "win32"

# ── DPI awareness ────────────────────────────────────────────────────────────
# Set once per process; Windows ignores every later attempt. `_dpi_lock` makes
# the "have we done this yet" check safe when the UI thread and a worker thread
# race to be first.
_dpi_lock = threading.Lock()
_dpi_done = False
_dpi_mode = "unset"


def ensure_dpi_awareness() -> str:
    """Declare this process DPI-aware, at the strongest mode available.

    Returns the mode that ended up applying, as a short string, so a caller can
    log it. Safe to call from anywhere and any number of times: only the first
    call does anything, and a failure is never fatal — the app still runs, it
    just measures the screen in the OS's scaled units instead of real pixels.

    Call this as the FIRST statement of main(), before QApplication is built.
    Qt sets PerMonitor-v1 for itself at construction and will not upgrade, so if
    Qt gets there first this can only ever fall back to v1.
    """
    global _dpi_done, _dpi_mode
    with _dpi_lock:
        if _dpi_done:
            return _dpi_mode
        _dpi_done = True

        if not _IS_WINDOWS:
            _dpi_mode = "not-windows"
            return _dpi_mode

        # PerMonitor-v2, and it has to be requested through
        # SetProcessDpiAwarenessContext. The obvious-looking alternative,
        # shcore.SetProcessDpiAwareness(2), is PROCESS_PER_MONITOR_DPI_AWARE —
        # which is PerMonitor **v1**, not v2. Both make GetProcessDpiAwareness
        # report 2, so the difference is invisible unless you compare the
        # context handle itself, which is how this was caught:
        #   shcore(2)                            -> NOT equal to PMv2
        #   SetProcessDpiAwarenessContext(-4)    -> equal to PMv2
        # v2 is what reports true physical pixels on a scaled display and what
        # rescales correctly when a window crosses between monitors of
        # different scaling.
        try:
            u = ctypes.windll.user32
            u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is the pseudo-handle -4.
            if u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4 & 0xFFFFFFFFFFFFFFFF)):
                _dpi_mode = "per-monitor-v2"
                return _dpi_mode
        except Exception:
            pass

        # PerMonitor v1 — Windows 8.1 and later.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _dpi_mode = "per-monitor-v1"
            return _dpi_mode
        except Exception:
            pass

        # System-DPI-aware: correct on a single display, wrong across monitors
        # of different scaling. Better than being unaware.
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_mode = "system-aware"
            return _dpi_mode
        except Exception:
            pass

        _dpi_mode = "unaware"
        return _dpi_mode


def dpi_mode() -> str:
    """What `ensure_dpi_awareness` settled on, or "unset" if never called."""
    return _dpi_mode


# ── Monitors ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Monitor:
    """One physical display, in physical pixels of the virtual desktop.

    `index` is mss's own numbering, which is what `capture(monitor=...)` takes.
    Note it starts at 1: mss's index 0 is the bounding box of every display
    combined, which is not a monitor anyone can point at.
    """
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False
    name: str = ""

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """(left, top, width, height) — the shape mss.grab accepts."""
        return (self.left, self.top, self.width, self.height)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def _mss_available() -> bool:
    return _mss is not None


def monitors() -> list[Monitor]:
    """Every physical display, primary first.

    mss's list already puts the primary at index 1, but it is sorted explicitly
    here so callers can rely on `monitors()[0]` being the primary rather than
    depending on an mss implementation detail.
    """
    if not _mss_available():
        # Last-ditch fallback so callers never have to handle None. Unaware
        # processes get scaled numbers here, which is exactly the bug this
        # module exists to avoid — hence the warning.
        if _IS_WINDOWS:
            u = ctypes.windll.user32
            w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
            print("[ScreenGeometry] mss unavailable; falling back to GetSystemMetrics "
                  "(coordinates may be DPI-scaled)")
            return [Monitor(1, 0, 0, w, h, True, "primary")]
        return [Monitor(1, 0, 0, 1920, 1080, True, "primary")]

    with _mss.MSS() as sct:
        raw = list(sct.monitors)
    if not raw:
        return []

    # raw[0] is the union of all displays; raw[1:] are the real ones.
    real = raw[1:] if len(raw) > 1 else raw
    out: list[Monitor] = []
    for i, m in enumerate(real, start=1):
        out.append(Monitor(
            index=i,
            left=int(m["left"]), top=int(m["top"]),
            width=int(m["width"]), height=int(m["height"]),
            is_primary=bool(m.get("is_primary", i == 1)),
            name=str(m.get("name", "")),
        ))
    out.sort(key=lambda m: (not m.is_primary, m.index))
    return out


def primary() -> Monitor:
    """The primary display. Never returns None; synthesises one if mss is out."""
    ms = monitors()
    if not ms:
        return Monitor(1, 0, 0, 1920, 1080, True, "primary")
    for m in ms:
        if m.is_primary:
            return m
    return ms[0]


def virtual_desktop() -> Monitor:
    """The bounding box of every display, as one Monitor.

    Its origin can be negative, which is why callers must not assume (0, 0).
    Use this to capture everything at once.
    """
    ms = monitors()
    if not ms:
        return primary()
    left = min(m.left for m in ms)
    top = min(m.top for m in ms)
    right = max(m.right for m in ms)
    bottom = max(m.bottom for m in ms)
    return Monitor(0, left, top, right - left, bottom - top, False, "virtual-desktop")


def monitor_for_point(x: int, y: int) -> Monitor:
    """Which display a physical point falls on, falling back to the nearest."""
    ms = monitors()
    for m in ms:
        if m.contains(x, y):
            return m
    if not ms:
        return primary()
    # Outside every display (a stale coordinate, or the gap between two
    # differently-sized monitors): pick whichever edge is closest, so a caller
    # gets a sane monitor to clamp into rather than a crash.
    def dist(m: Monitor) -> int:
        dx = max(m.left - x, 0, x - m.right)
        dy = max(m.top - y, 0, y - m.bottom)
        return dx * dx + dy * dy
    return min(ms, key=dist)


# ── Physical <-> logical ─────────────────────────────────────────────────────
# Qt positions top-level windows in logical pixels; everything in this module is
# physical. The ratio is per-monitor, so the caller says which monitor the point
# is on and this reads that monitor's Qt screen. Imported lazily because this
# module is imported before QApplication exists.

def _qt_screen_for(monitor: Monitor | None):
    try:
        from PyQt6.QtGui import QGuiApplication
    except ImportError:
        return None, 1.0
    app = QGuiApplication.instance()
    if app is None:
        return None, 1.0
    screens = app.screens()
    if not screens:
        return None, 1.0

    target = monitor or primary()
    # Match on the screen's PHYSICAL geometry against the monitor's rect. Qt
    # reports screen geometry in logical pixels, so multiply back by the ratio
    # to compare like with like.
    for s in screens:
        g = s.geometry()
        dpr = float(s.devicePixelRatio() or 1.0)
        if (round(g.left() * dpr), round(g.top() * dpr),
                round(g.width() * dpr), round(g.height() * dpr)) == target.rect:
            return s, dpr
    # No exact match (monitor layout changed since Qt started): fall back to
    # the screen whose physical origin is closest to the monitor's.
    def dist(s) -> int:
        g = s.geometry()
        dpr = float(s.devicePixelRatio() or 1.0)
        return abs(round(g.left() * dpr) - target.left) + abs(round(g.top() * dpr) - target.top)
    s = min(screens, key=dist)
    return s, float(s.devicePixelRatio() or 1.0)


def scale_factor(monitor: Monitor | None = None) -> float:
    """That monitor's Qt device-pixel-ratio. 1.0 when Qt is not running.

    This is the number to divide by when turning a physical measurement into
    something `setGeometry` will honour.
    """
    _, dpr = _qt_screen_for(monitor)
    return dpr or 1.0


def to_logical(x: int, y: int) -> tuple[int, int]:
    """Physical point -> Qt logical point, for positioning a window.

    On a 150%-scaled 1920x1080 screen this maps 960,540 -> 640,360. A top-level
    window given the physical value would draw half a screen away from the
    target.
    """
    mon = monitor_for_point(x, y)
    dpr = scale_factor(mon)
    if dpr == 1.0:
        return x, y
    screen, _ = _qt_screen_for(mon)
    if screen is None:
        return round(x / dpr), round(y / dpr)
    g = screen.geometry()
    # Convert into the screen's own logical origin: a monitor to the right of
    # the primary has a physical origin of e.g. 1920, but a logical origin of
    # 1920/dpr, and both have to be subtracted consistently.
    lx = g.left() + round((x - mon.left) / dpr)
    ly = g.top() + round((y - mon.top) / dpr)
    return lx, ly


def to_physical(x: int, y: int) -> tuple[int, int]:
    """Qt logical point -> physical point. The inverse of `to_logical`."""
    try:
        from PyQt6.QtGui import QGuiApplication
    except ImportError:
        return x, y
    app = QGuiApplication.instance()
    if app is None:
        return x, y
    screen = app.screenAt(_qt_point(x, y)) or app.primaryScreen()
    if screen is None:
        return x, y
    dpr = float(screen.devicePixelRatio() or 1.0)
    g = screen.geometry()
    px = round(g.left() * dpr) + round((x - g.left()) * dpr)
    py = round(g.top() * dpr) + round((y - g.top()) * dpr)
    return px, py


def _qt_point(x: int, y: int):
    from PyQt6.QtCore import QPoint
    return QPoint(x, y)


def logical_rect(physical_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Convert a physical box to Qt logical pixels, as (x, y, width, height).

    Takes (left, top, RIGHT, BOTTOM) — the same convention `ui_grounding`'s
    `Candidate.rect` uses, and the one the accessibility tree, OCR and the
    vision layer all report. Returns (x, y, width, height), which is what
    `QWidget.setGeometry` wants.

    The two conventions are easy to confuse, and confusing them is not a subtle
    error: passing a right/bottom pair where a width/height is expected makes
    the box as large as the coordinate itself, so a 260x60 target draws as
    860x510. `capture(region=...)` takes (left, top, width, height), which is
    where the inconsistency comes from — it is the one place that differs.
    """
    l, t, r, b = physical_rect
    lx, ly = to_logical(l, t)
    dpr = scale_factor(monitor_for_point(l, t))
    return lx, ly, round((r - l) / dpr), round((b - t) / dpr)


# ── Cursor ───────────────────────────────────────────────────────────────────

def cursor_pos() -> tuple[int, int]:
    """The mouse position in physical pixels. (0, 0) if it cannot be read."""
    if not _IS_WINDOWS:
        return 0, 0
    try:
        class _P(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = _P()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return int(p.x), int(p.y)
    except Exception:
        return 0, 0


def _cursor_bitmap():
    """The current cursor as (hicon, hotspot_x, hotspot_y), or None.

    Uses GetCursorInfo, which reports the *displayed* cursor — so it is correct
    for a cursor loaded from a custom scheme, and correct while a drag is in
    progress. GetIconInfo then yields the hotspot, which is the offset from the
    bitmap's top-left to the actual pointing pixel; without it the cursor is
    drawn down-and-right of where the user sees it.
    """
    if not _IS_WINDOWS:
        return None
    try:
        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class _CURSORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint32),
                ("flags", ctypes.c_uint32),
                ("hCursor", ctypes.c_void_p),
                ("ptScreenPos", _POINT),
            ]

        class _ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", ctypes.c_bool),
                ("xHotspot", ctypes.c_uint32),
                ("yHotspot", ctypes.c_uint32),
                ("hbmMask", ctypes.c_void_p),
                ("hbmColor", ctypes.c_void_p),
            ]

        u = ctypes.windll.user32
        # argtypes matter here: without them ctypes assumes C int, and on 64-bit
        # Windows that truncates the handle and GetIconInfo fails outright.
        u.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
        u.GetCursorInfo.restype = ctypes.c_bool
        u.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ICONINFO)]
        u.GetIconInfo.restype = ctypes.c_bool

        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(_CURSORINFO)
        if not u.GetCursorInfo(ctypes.byref(ci)):
            return None
        if not ci.hCursor or not (ci.flags & 0x00000001):  # CURSOR_SHOWING
            return None
        ii = _ICONINFO()
        if not u.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
            return None
        # GetIconInfo allocates two bitmaps that the caller owns.
        gdi = ctypes.windll.gdi32
        gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        for bm in (ii.hbmMask, ii.hbmColor):
            if bm:
                gdi.DeleteObject(bm)
        # Returned as a plain int handle; callers pass it straight back into
        # DrawIconEx, which is declared with the matching argtype.
        return (int(ci.hCursor), int(ii.xHotspot), int(ii.yHotspot))
    except Exception:
        return None


def _cursor_enabled() -> bool:
    """Whether the user wants the pointer drawn into captures.

    Read through the config manager rather than a module-level constant so a
    change in the UI takes effect on the next capture, without a restart. Any
    failure means "yes" — the cursor is the more useful default.
    """
    try:
        from memory.config_manager import get_cursor_in_capture
        return get_cursor_in_capture()
    except Exception:
        return True


def cursor_in_capture(img, origin: tuple[int, int] | None = None):
    """Draw the real mouse cursor onto a capture, at its true position.

    mss does not composite the cursor on Windows (there is no cursor path in its
    win32 backend at all), so a screenshot is a picture of a desktop with no
    mouse in it. That makes any instruction that refers to where the pointer
    already is — "click just left of the cursor", "drag from here" — impossible
    for the model to act on, and hides the one landmark the user can see.

    `origin` is the physical (left, top) the image starts at, so the cursor is
    placed correctly for a crop as well as a full capture.
    """
    if not _PIL or img is None:
        return img
    info = _cursor_bitmap()
    if info is None:
        return img
    hicon, hot_x, hot_y = info
    cx, cy = cursor_pos()
    ox, oy = origin or (0, 0)

    try:
        size = _cursor_size()
        icon = _hicon_to_image(hicon, size)
        if icon is None:
            return img
        # Hotspot is in cursor pixels; scale it if the icon came back at a
        # different size than the system reports.
        sx = icon.width / max(size, 1)
        px = int((cx - ox) - hot_x * sx)
        py = int((cy - oy) - hot_y * sx)
        # Only composite when it lands inside the image; a cursor outside a crop
        # is normal and not an error.
        if px + icon.width < 0 or py + icon.height < 0:
            return img
        if px > img.width or py > img.height:
            return img
        img.paste(icon, (px, py), icon)
    except Exception:
        return img
    return img


def _cursor_size() -> int:
    """The system cursor's pixel size, from the registry-backed metric.

    SM_CXCURSOR is in the process's DPI units, so multiply by the system scale
    to get real pixels on a scaled display.
    """
    try:
        u = ctypes.windll.user32
        base = int(u.GetSystemMetrics(13)) or 32  # SM_CXCURSOR
        dpi = int(u.GetDpiForSystem()) if hasattr(u, "GetDpiForSystem") else 96
        return max(16, round(base * (dpi / 96.0)))
    except Exception:
        return 32


def _hicon_to_image(hicon, size: int):
    """Render an HICON into a PIL image via a 32-bit DIB section.

    Drawing through a memory DC into a DIB is what preserves the alpha channel
    of a modern cursor; the older DrawIcon path silently produces a black box
    behind cursors that have one.
    """
    import ctypes

    u = ctypes.windll.user32
    gdi = ctypes.windll.gdi32

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    # Every one of these returns a 64-bit handle on 64-bit Windows, so the
    # restypes have to be declared or ctypes truncates them to C int and the
    # calls fail (or worse, succeed against a garbage handle).
    u.GetDC.argtypes = [ctypes.c_void_p]
    u.GetDC.restype = ctypes.c_void_p
    u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    u.DrawIconEx.restype = ctypes.c_bool
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                     ctypes.c_uint]
    gdi.CreateDIBSection.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    # Negative height => a top-down DIB, matching PIL's row order.
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    hdc_screen = u.GetDC(None)
    hdc_mem = gdi.CreateCompatibleDC(hdc_screen)
    bits = ctypes.c_void_p()
    hbmp = gdi.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                ctypes.byref(bits), None, 0)
    if not hbmp:
        gdi.DeleteDC(hdc_mem)
        u.ReleaseDC(None, hdc_screen)
        return None
    old = gdi.SelectObject(hdc_mem, hbmp)
    try:
        # DI_NORMAL (3) draws the colour bitmap through the mask, and on a
        # 32-bit DIB the icon's own alpha comes through too.
        u.DrawIconEx(hdc_mem, 0, 0, ctypes.c_void_p(hicon), size, size, 0, None, 3)
        buf = ctypes.string_at(bits, size * size * 4)
    finally:
        gdi.SelectObject(hdc_mem, old)
        gdi.DeleteObject(hbmp)
        gdi.DeleteDC(hdc_mem)
        u.ReleaseDC(None, hdc_screen)

    img = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1).copy()
    return img


# ── Capture ──────────────────────────────────────────────────────────────────

def capture(monitor: Monitor | int | None = None,
            with_cursor: bool = True,
            max_px: int | None = None,
            region: tuple[int, int, int, int] | None = None):
    """Grab the screen. Returns (PIL.Image, origin) where origin is the physical
    (left, top) the image starts at.

    `monitor` accepts a Monitor, an mss index, or None for the primary display.
    `region` is a physical (left, top, width, height) crop and takes precedence
    over `monitor`. `max_px` caps the LONGEST side, preserving aspect ratio —
    note that the old code capped width only, so a tall display was never
    resized and behaved differently from a wide one.

    The origin is the important part: a crop of the bottom-right of a secondary
    monitor has a large positive origin, and every coordinate derived from the
    image has to be shifted by it to become a real screen coordinate. Forgetting
    that shift is what made the previous implementation able to find an element
    and still click in the wrong place.
    """
    if _mss is None:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    if region is not None:
        left, top, width, height = (int(v) for v in region)
    else:
        if isinstance(monitor, Monitor):
            left, top, width, height = monitor.rect
        elif isinstance(monitor, int):
            with _mss.MSS() as sct:
                ms = list(sct.monitors)
            if monitor < 0 or monitor >= len(ms):
                raise ValueError(f"monitor index {monitor} out of range (0-{len(ms) - 1})")
            m = ms[monitor]
            left, top, width, height = (int(m["left"]), int(m["top"]),
                                        int(m["width"]), int(m["height"]))
        else:
            m = primary()
            left, top, width, height = m.rect

    with _mss.MSS() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})

    if not _PIL:
        raise RuntimeError("pillow is not installed. Run: pip install pillow")

    img = Image.frombytes("RGB", shot.size, shot.rgb)

    if with_cursor and _cursor_enabled():
        img = cursor_in_capture(img, (left, top))

    if max_px and max(img.size) > max_px:
        scale = max_px / max(img.size)
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.BILINEAR)

    return img, (left, top)


def capture_jpeg(monitor: Monitor | int | None = None,
                 with_cursor: bool = True,
                 max_px: int | None = 1600,
                 quality: int = 85,
                 region: tuple[int, int, int, int] | None = None
                 ) -> tuple[bytes, tuple[int, int], tuple[int, int]]:
    """Capture and encode to JPEG in one step.

    Returns (jpeg_bytes, origin, (width, height)) where the width/height are of
    the ENCODED image. A caller that sends this to a model and gets a
    normalised box back needs the encoded size to convert, not the screen size —
    which is exactly the confusion that made the old finder unreliable.

    `region` is a physical (left, top, width, height) crop and takes precedence
    over `monitor`, same as `capture`. The origin that comes back is the crop's
    own top-left, which is what a model's box has to be mapped through.
    """
    import io
    img, origin = capture(monitor=monitor, with_cursor=with_cursor,
                          max_px=max_px, region=region)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), origin, img.size


def grab_rect(rect: tuple[int, int, int, int], with_cursor: bool = False):
    """Small crop, for verifying that a click changed what it was aimed at."""
    img, _ = capture(region=rect, with_cursor=with_cursor)
    return img


def changed_pixels(before, after, tolerance: int = 12) -> int:
    """How many pixels differ between two captures.

    A count, not a fraction, and that is a deliberate correction. A fraction
    threshold sounds safer but is far too coarse: a label changing from "0" to
    "1" is about 40 pixels, which in a 560x300 window is 0.02% — ten times below
    any threshold loose enough to tolerate a busy screen, so a real, successful
    click was scored as having done nothing.

    A count works because captures are deterministic: two grabs of an unchanged
    window differ by exactly zero pixels (measured, repeatedly). There is no
    noise to tolerate, so a handful of changed pixels is already meaningful.

    `tolerance` is the per-channel difference that counts as changed at all,
    which filters antialiasing and dithering on content that has not really
    moved.
    """
    try:
        import numpy as np
        a = np.asarray(before.convert("RGB"), dtype=np.int16)
        b = np.asarray(after.convert("RGB"), dtype=np.int16)
        if a.shape != b.shape:
            return 1 << 30
        return int((np.abs(a - b).max(axis=2) > tolerance).sum())
    except Exception:
        return 1 << 30


def changed_fraction(before, after, tolerance: int = 12) -> float:
    """Fraction of pixels that differ, 0..1. Kept for reporting."""
    try:
        import numpy as np
        a = np.asarray(before.convert("RGB"), dtype=np.int16)
        b = np.asarray(after.convert("RGB"), dtype=np.int16)
        if a.shape != b.shape:
            return 1.0
        return float((np.abs(a - b).max(axis=2) > tolerance).mean())
    except Exception:
        return 1.0


# A change smaller than this many pixels is treated as noise. The measured floor
# is zero, so this only has to clear genuine small artefacts — a caret, a
# subpixel-shifted glyph — while staying well under the ~40 px a single
# character change produces.
_MIN_CHANGED_PX = 24


class ChangeWatch:
    """Watch for the screen changing in response to an action.

    Two regions are watched, and the reason is a bug this was written to fix.

    Watching only the neighbourhood of the click is precise — a clock ticking in
    another window cannot make a missed click look like a hit. But it is also
    blind: clicking a counter's "+" button changes a label at the top of the
    window, not the button, so a click that worked perfectly was reported as
    having done nothing. An agent that believes that retries, and the retry
    clicks a button that was already clicked — which is how a two-click goal
    ended up clicking four times.

    So a change in EITHER region counts, and the result says which one moved.
    The local region is the strong signal; the window region is what stops a
    working action being called a failure. Only the foreground window is watched
    for the wide check, which keeps an unrelated window's activity out of it.

    A change must also PERSIST to count. A blinking text caret produces the same
    ~40 px signal as a real change, so a single sample cannot tell them apart;
    sampling twice and requiring both to show it does, because a blink toggles
    off again between the two.
    """

    def __init__(self, local: tuple[int, int, int, int] | None,
                 wide: tuple[int, int, int, int] | None = None):
        self.local = local
        self.wide = wide
        self._before_local = None
        self._before_wide = None

    def snapshot(self) -> None:
        """Capture the before-state. Call immediately before acting."""
        self._before_local = self._grab(self.local)
        # Skip the wide capture when it is the same area as the local one, or
        # when the local region already covers the window.
        if self.wide and self.wide != self.local:
            self._before_wide = self._grab(self.wide)

    @staticmethod
    def _grab(rect):
        if not rect:
            return None
        try:
            img, _ = capture(region=rect, with_cursor=False)
            return img
        except Exception:
            return None

    def changed(self, settle_s: float = 0.35,
                retry_s: float = 0.9) -> tuple[bool, float, str]:
        """Has anything changed since the snapshot, and did it stay changed?

        Waits `settle_s`, measures; waits `retry_s` more and measures again.

        * Changed at both samples — a real, persistent change.
        * Changed only at the second — a slow response, still a success.
        * Changed only at the first — a transient, such as a caret blinking on
          and off again. Not a change.

        Returns (changed, fraction, where).
        """
        import time as _t

        _t.sleep(settle_s)
        first, where = self._measure()
        _t.sleep(retry_s)
        second, where2 = self._measure()

        if first >= _MIN_CHANGED_PX and second >= _MIN_CHANGED_PX:
            return True, max(first, second) / self._area(), where or where2
        if second >= _MIN_CHANGED_PX:
            return True, second / self._area(), where2
        return False, max(first, second) / self._area(), ""

    def _area(self) -> int:
        r = self.local or self.wide
        if not r:
            return 1
        return max(1, r[2] * r[3])

    def _measure(self) -> tuple[int, str]:
        """Changed-pixel count, and a phrase naming which region moved."""
        if self._before_local is not None:
            after = self._grab(self.local)
            if after is not None:
                n = changed_pixels(self._before_local, after)
                if n >= _MIN_CHANGED_PX:
                    return n, "where it was clicked"
        if self._before_wide is not None:
            after = self._grab(self.wide)
            if after is not None:
                n = changed_pixels(self._before_wide, after)
                if n >= _MIN_CHANGED_PX:
                    return n, "elsewhere in the window"
        return 0, ""


def watch_for(local: tuple[int, int, int, int] | None,
              wide: tuple[int, int, int, int] | None = None) -> ChangeWatch:
    """Build a ChangeWatch for a click at `local`, falling back to the
    foreground window for the wide region when the caller has none."""
    if wide is None:
        try:
            from core import ui_grounding
            fg = ui_grounding.foreground_window()
            if fg is not None:
                wide = fg[1]
        except Exception:
            wide = None
    return ChangeWatch(local, wide)


def describe() -> str:
    """A one-line summary for the log — the thing to read when a click misses."""
    ms = monitors()
    parts = [f"dpi={dpi_mode()}"]
    for m in ms:
        parts.append(f"#{m.index}{'(primary)' if m.is_primary else ''} "
                     f"{m.width}x{m.height}@{m.left},{m.top}"
                     f"{' scale=' + str(scale_factor(m)) if scale_factor(m) != 1.0 else ''}")
    vd = virtual_desktop()
    parts.append(f"virtual={vd.width}x{vd.height}@{vd.left},{vd.top}")
    return " | ".join(parts)
