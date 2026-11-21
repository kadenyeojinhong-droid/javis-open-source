"""Javis HUD (lite): a floating glass capsule with the four agents and their activity animations.

Everything else (orders, settings, approvals) happens in the terminal; see approve.py for approvals.
Run:  .venv\\Scripts\\pythonw.exe hud_lite.py [--hidden]
Env:  HUD_CAPTURE_VISIBLE=1  let screenshots see the HUD (review only; the glass then shows a bit of itself)
"""
import argparse
import ctypes
import ctypes.wintypes
import json
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QRect, Qt, QTimer, QUrl, Property, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QGuiApplication, QImage, QRegion
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkRequest
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow, QSGRendererInterface
from PySide6.QtWebSockets import QWebSocket

ROOT = Path(__file__).resolve().parent
API = "http://127.0.0.1:8765"
POS_FILE = ROOT / ".ai_bus" / "hud_pos.json"
AGENT_IDS = ["claude", "agy", "codex", "deepseek"]


# ---------- global hotkeys: own thread + RegisterHotKey(NULL), the only variant proven to work here ----------
class HotkeySignals(QObject):
    pressed = Signal(int)


class Hotkeys:
    MOD = 0x0002 | 0x0001 | 0x4000  # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT (0x0004 is Shift, not Alt)

    def __init__(self):
        self.signals = HotkeySignals()
        self.thread_id = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(5)

    def stop(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
            self.thread.join(2)

    def _run(self):
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = ctypes.wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the message queue
        registered = [i for i, key in ((1, ord("A")), (2, ord("T"))) if user32.RegisterHotKey(None, i, self.MOD, key)]
        self.ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    self.signals.pressed.emit(int(msg.wParam))
        finally:
            for i in registered:
                user32.UnregisterHotKey(None, i)


# ---------- frosted glass: blur of the desktop right behind the capsule ----------
class GlassProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage()

    def requestImage(self, image_id, size, requested_size):
        return self.image


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.wintypes.LONG),
                ("biHeight", ctypes.wintypes.LONG), ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.wintypes.LONG),
                ("biYPelsPerMeter", ctypes.wintypes.LONG), ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.wintypes.DWORD * 3)]


def _bgra_to_image(pixels, width, height):
    """Copy a top-down 32-bit GDI BGRA buffer into an owned Qt image."""
    image = QImage(bytes(pixels), width, height, width * 4, QImage.Format_ARGB32)
    return image.copy()


def _gdi_capture(left, top, width, height, dpr):
    """Capture a logical desktop rectangle using GDI; safe to call off the GUI thread."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.argtypes = (ctypes.wintypes.HWND,)
    user32.GetDC.restype = ctypes.wintypes.HDC
    user32.ReleaseDC.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.HDC)
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = (ctypes.wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = (ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi32.CreateCompatibleBitmap.restype = ctypes.wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (ctypes.wintypes.HDC, ctypes.wintypes.HANDLE)
    gdi32.SelectObject.restype = ctypes.wintypes.HANDLE
    gdi32.BitBlt.argtypes = (ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.wintypes.DWORD)
    gdi32.BitBlt.restype = ctypes.wintypes.BOOL
    gdi32.GetDIBits.argtypes = (ctypes.wintypes.HDC, ctypes.wintypes.HBITMAP, ctypes.wintypes.UINT,
                                ctypes.wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.UINT)
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = (ctypes.wintypes.HANDLE,)
    gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
    gdi32.DeleteDC.argtypes = (ctypes.wintypes.HDC,)
    gdi32.DeleteDC.restype = ctypes.wintypes.BOOL
    px, py = round(left * dpr), round(top * dpr)
    pw, ph = max(1, round(width * dpr)), max(1, round(height * dpr))
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return QImage()
    mem_dc = bitmap = old = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, pw, ph)
        if not mem_dc or not bitmap:
            return QImage()
        old = gdi32.SelectObject(mem_dc, bitmap)
        if not gdi32.BitBlt(mem_dc, 0, 0, pw, ph, screen_dc, px, py, 0x00CC0020):
            return QImage()
        info = _BITMAPINFO()
        info.bmiHeader = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), pw, -ph, 1, 32, 0, pw * ph * 4, 0, 0, 0, 0)
        pixels = (ctypes.c_ubyte * (pw * ph * 4))()
        if not gdi32.GetDIBits(mem_dc, bitmap, 0, ph, pixels, ctypes.byref(info), 0):
            return QImage()
        return _bgra_to_image(pixels, pw, ph)
    finally:
        if old and mem_dc:
            gdi32.SelectObject(mem_dc, old)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def set_affinity(window, value):
    fn = ctypes.windll.user32.SetWindowDisplayAffinity
    fn.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
    fn(ctypes.wintypes.HWND(int(window.winId())), value)


def exclude_from_capture(window):
    # our own pixels must not end up in the snapshot we blur
    if sys.platform == "win32" and not os.environ.get("HUD_CAPTURE_VISIBLE"):
        set_affinity(window, 0x11)  # WDA_EXCLUDEFROMCAPTURE


# ---------- bridge between hud_server and QML ----------
class Hud(QObject):
    stateChanged = Signal()
    planeSent = Signal(str, str)        # sender, receiver
    glassChanged = Signal()
    brightChanged = Signal()            # desktop behind the capsule turned bright/dark: QML switches glass style
    attention = Signal()                # something the user should see: show the capsule
    _capture_done = Signal(object, float, object, bool)

    def __init__(self, window_getter):
        super().__init__()
        self._window = window_getter
        self._agents = [{"id": i, "name": i, "color": "#ffffff"} for i in AGENT_IDS]
        self._busy, self._queues, self._breaker, self._limit, self._idle = [], {}, 0, 10, 15
        self._standins = []
        self._models = {}
        self._glass_rev = 0
        self._next_grab = 0.0
        self._capture_lock = threading.Lock()
        self._capture_done.connect(self._finish_capture, Qt.QueuedConnection)
        self._grab_ms = 0.0
        self._mask = QRegion()
        self._glass_rect = {"x": 0, "y": 0, "w": 0, "h": 0}
        self._bright, self._lum = False, -1.0
        self.provider = GlassProvider()
        self.net = QNetworkAccessManager(self)
        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._on_ws)
        self.ws.disconnected.connect(lambda: QTimer.singleShot(2000, self._connect))
        self._connect()

    # --- server I/O ---
    def _connect(self):
        self.ws.open(QUrl(API.replace("http", "ws") + "/ws"))
        self.fetch_state()

    def fetch_state(self):
        reply = self.net.get(QNetworkRequest(QUrl(API + "/state")))
        reply.finished.connect(lambda: self._on_state(reply))

    def _on_state(self, reply):
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except ValueError:
            return
        finally:
            reply.deleteLater()
        self._apply_state(data)

    def _apply_state(self, data):
        if os.environ.get("HUD_DEMO"):
            return  # demo drives the state itself
        if data.get("agents"):
            self._agents = [a for a in data["agents"] if a.get("id") in AGENT_IDS]
        self._busy = list(data.get("busy", []))
        self._standins = list((data.get("standins") or {}).keys())
        self._models = dict(data.get("models") or {})
        self._queues = dict(data.get("queues", {}))
        self._breaker = sum((data.get("breaker") or {}).values())
        settings = data.get("settings") or {}
        self._limit = int(settings.get("breaker_limit", 10))
        self._idle = int(settings.get("idle_seconds", 15)) if settings.get("auto_hide", True) else 0
        if data.get("approvals") or self._breaker >= self._limit:
            self.attention.emit()
        self.stateChanged.emit()

    def _on_ws(self, text):
        try:
            payload = json.loads(text)
        except ValueError:
            return
        for event in payload if isinstance(payload, list) else [payload]:
            kind = event.get("type")
            if kind == "state":
                self._apply_state(event)
            elif kind == "activity" and event.get("action") == "sent" and event.get("receiver") in AGENT_IDS:
                self.planeSent.emit(event.get("sender", ""), event["receiver"])
                self.fetch_state()
            elif kind in ("completed", "failed"):
                if kind == "failed":
                    self.attention.emit()
                self.fetch_state()

    # --- properties for QML ---
    @Property("QVariantList", notify=stateChanged)
    def agents(self):
        return self._agents

    @Property("QVariantList", notify=stateChanged)
    def busy(self):
        return self._busy

    @Property("QVariantList", notify=stateChanged)
    def standins(self):
        return self._standins

    @Property("QVariantMap", notify=stateChanged)
    def models(self):
        return self._models  # {slot: {"model", "purpose"}} for model calls in flight

    @Property("QVariantMap", notify=stateChanged)
    def queues(self):
        return self._queues

    @Property(int, notify=stateChanged)
    def breaker(self):
        return self._breaker

    @Property(int, notify=stateChanged)
    def limit(self):
        return self._limit

    @Property(int, notify=stateChanged)
    def idleSeconds(self):
        return self._idle

    @Property(int, notify=glassChanged)
    def glassRev(self):
        return self._glass_rev

    @Property("QVariantMap", notify=glassChanged)
    def glassRect(self):
        return self._glass_rect

    @Property(bool, notify=brightChanged)
    def bgBright(self):
        return self._bright

    # --- glass snapshot ---
    @Slot(int, int, int, int, int)
    def captureGlass(self, x, y, w, h, pad):
        """x, y, w, h: the capsule rect in window coordinates (logical px). Grabs that rect plus `pad` around it, raw:
        QML (MultiEffect) blurs, tints and clips it on the GPU, so the GUI thread only pays for the grab itself."""
        window = self._window()
        if window is None or not window.isVisible() or w <= 0 or h <= 0:
            return
        if time.monotonic() < self._next_grab:
            return  # last grab was slow (busy PC): back off instead of stalling the UI thread
        screen = window.screen()
        origin = window.position()
        sg = screen.geometry()
        # clamp to the screen so no black off-screen band gets blurred in
        left, top = max(sg.x(), origin.x() + x - pad), max(sg.y(), origin.y() + y - pad)
        right, bottom = min(sg.right() + 1, origin.x() + x + w + pad), min(sg.bottom() + 1, origin.y() + y + h + pad)
        if right <= left or bottom <= top:
            return
        if not self._capture_lock.acquire(blocking=False):
            return
        review = sys.platform == "win32" and os.environ.get("HUD_CAPTURE_VISIBLE")
        if review:  # review screenshots: hide from capture just for our own grab, so the glass is not fed its own pixels
            set_affinity(window, 0x11)
            time.sleep(0.06)  # let DWM recompose without us (review mode only)
        if sys.platform != "win32" and not review:
            t0 = time.monotonic()
            try:
                img = screen.grabWindow(0, left - sg.x(), top - sg.y(), right - left, bottom - top).toImage()
                self._finish_capture(img, time.monotonic() - t0,
                                     (left - origin.x(), top - origin.y(), right - left, bottom - top), False)
            finally:
                self._capture_lock.release()
            return
        if review:
            t0 = time.monotonic()
            try:
                img = screen.grabWindow(0, left - sg.x(), top - sg.y(), right - left, bottom - top).toImage()
            finally:
                set_affinity(window, 0)
            try:
                self._finish_capture(img, time.monotonic() - t0, (left - origin.x(), top - origin.y(), right - left, bottom - top), False)
            finally:
                self._capture_lock.release()
            return
        t0 = time.monotonic()
        rect = (left - origin.x(), top - origin.y(), right - left, bottom - top)
        dpr = screen.devicePixelRatio()

        def capture():
            try:
                img = _gdi_capture(left, top, right - left, bottom - top, dpr)
                self._capture_done.emit(img, time.monotonic() - t0, rect, True)
            except Exception:
                self._capture_done.emit(QImage(), time.monotonic() - t0, rect, True)
        try:
            threading.Thread(target=capture, name="hud-glass-capture", daemon=True).start()
        except RuntimeError:
            self._capture_lock.release()
            raise

    @Slot(object, float, object, bool)
    def _finish_capture(self, img, cost, rect, release=True):
        if release:
            self._capture_lock.release()
        if img.isNull():
            return
        tiny = img.scaled(8, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        lum = sum(QColor(tiny.pixel(i, j)).lightnessF() for i in range(8) for j in range(8)) / 64
        self._lum = lum
        bright = lum > 0.45 if self._bright else lum > 0.6  # hysteresis: no flicker on mid-grey backgrounds
        if bright != self._bright:
            self._bright = bright
            self.brightChanged.emit()
        # half size is plenty under a GPU blur and halves the texture upload
        self.provider.image = img.scaled(max(1, img.width() // 2), max(1, img.height() // 2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        rx, ry, rw, rh = rect
        self._glass_rect = {"x": rx, "y": ry, "w": rw, "h": rh}
        self._grab_ms = max(self._grab_ms, cost * 1000)
        self._next_grab = time.monotonic() + (min(20.0, cost * 200) if cost > 0.03 else 0)
        self._glass_rev += 1
        self.glassChanged.emit()

    # --- window input region: only the capsule (and live extras) take clicks; the rest of the window is the desktop's ---
    @Slot("QVariantList")
    def setInputRegion(self, rects):
        window = self._window()
        if window is None:
            return
        region = QRegion()
        for r in rects:
            region = region.united(QRegion(QRect(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))))
        if region == self._mask:
            return  # SetWindowRgn makes DWM recompose the window (up to ~75 ms): never repeat an identical one
        self._mask = region
        window.setMask(region)

    # --- persistence ---
    @Slot(result="QVariantMap")
    def loadPos(self):
        try:
            return json.loads(POS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @Slot(str, int)
    def savePos(self, side, offset):
        POS_FILE.parent.mkdir(parents=True, exist_ok=True)
        POS_FILE.write_text(json.dumps({"side": side, "offset": offset}), encoding="utf-8")

    @Slot(result=QPoint)
    def cursorPos(self):
        # absolute cursor position; dragging from mapToGlobal() fed the moving window's own lag back in (capsule ran off)
        return QCursor.pos()

    @Slot(int, int)
    def moveWindow(self, x, y):
        # one atomic move: QML's `x = ..; y = ..` is two separate window moves, which DWM shows as a 1-frame zigzag
        window = self._window()
        if window is not None and (window.x() != x or window.y() != y):
            window.setPosition(x, y)

    @Slot()
    def openTerminal(self):  # Ctrl+Alt+T: the 2x2 Javis terminal (one live pane per agent)
        req = QNetworkRequest(QUrl(API + "/workbench"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        reply = self.net.post(req, b"{}")
        reply.finished.connect(reply.deleteLater)

    @Slot()
    def toggleConsole(self):
        req = QNetworkRequest(QUrl(API + "/console"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        state = self.net.get(QNetworkRequest(QUrl(API + "/console")))

        def flip():
            try:
                visible = json.loads(bytes(state.readAll()).decode()).get("visible", False)
            except ValueError:
                visible = False
            state.deleteLater()
            self.net.post(req, json.dumps({"show": not visible}).encode())
        state.finished.connect(flip)


class ResumeFilter(QAbstractNativeEventFilter):
    """Calls on_wake after system resume (WM_POWERBROADCAST) or display change (WM_DISPLAYCHANGE)."""
    def __init__(self, on_wake):
        super().__init__()
        self.on_wake = on_wake

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if (msg.message == 0x0218 and msg.wParam in (0x7, 0x12)) or msg.message == 0x007E:
                self.on_wake()
        return False, 0


def stay_responsive():
    """Busy PC: keep the HUD scheduled. Above-normal priority + opt out of Win11 EcoQoS throttling (hidden pythonw gets it)."""
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    k32.SetPriorityClass.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD)
    k32.SetPriorityClass(k32.GetCurrentProcess(), 0x8000)  # ABOVE_NORMAL_PRIORITY_CLASS

    class PowerThrottling(ctypes.Structure):
        _fields_ = [("Version", ctypes.wintypes.ULONG), ("ControlMask", ctypes.wintypes.ULONG), ("StateMask", ctypes.wintypes.ULONG)]
    state = PowerThrottling(1, 0x1, 0)  # control EXECUTION_SPEED, state off = never throttle
    k32.SetProcessInformation.argtypes = (ctypes.wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.wintypes.DWORD)
    k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state))  # 4 = ProcessPowerThrottling


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hidden", action="store_true")
    args = parser.parse_args()

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QGuiApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    # single instance: a second launch just toggles the running one
    sock = QLocalSocket()
    sock.connectToServer("javis-hud-lite")
    if sock.waitForConnected(250):
        sock.write(b"toggle")
        sock.flush()
        sock.waitForBytesWritten(500)
        return 0
    QLocalServer.removeServer("javis-hud-lite")
    server = QLocalServer()
    server.listen("javis-hud-lite")

    for f in sorted((ROOT / "ui" / "fonts").glob("Inter-*.ttf")):
        QFontDatabase.addApplicationFont(str(f))
    font = QFont("Inter", 10)
    font.setFamilies(["Inter", "Microsoft YaHei UI"])
    app.setFont(font)

    holder = {}
    hud = Hud(lambda: holder.get("window"))
    engine = QQmlApplicationEngine()
    engine.addImageProvider("glass", hud.provider)
    engine.rootContext().setContextProperty("hud", hud)
    engine.load(str(ROOT / "ui" / "lite" / "Capsule.qml"))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    holder["window"] = window
    exclude_from_capture(window)

    toggle = lambda: window.metaObject().invokeMethod(window, "toggleShown")  # noqa: E731
    server.newConnection.connect(lambda: (server.nextPendingConnection().readyRead.connect(toggle)))

    # After sleep/resume or a display change the D3D11 swap chain can be lost: window stays "visible" but draws nothing.
    def recover():
        if window.isVisible():
            window.releaseResources()
            window.hide()
            window.show()
        window.update()
    filt = ResumeFilter(lambda: QTimer.singleShot(2000, recover))
    app.installNativeEventFilter(filt)

    hotkeys = Hotkeys()
    hotkeys.signals.pressed.connect(lambda i: toggle() if i == 1 else hud.openTerminal(), Qt.QueuedConnection)
    hotkeys.start()
    app.aboutToQuit.connect(hotkeys.stop)

    def trim():
        # hand idle pages back to Windows (they come back on demand); keeps the HUD light on a 16 GB machine
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE  # 64-bit: the pseudo-handle must stay pointer-sized
        k32.SetProcessWorkingSetSize.argtypes = (ctypes.wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t)
        k32.SetProcessWorkingSetSize(k32.GetCurrentProcess(), ctypes.c_size_t(-1).value, ctypes.c_size_t(-1).value)
    # once only: periodic / on-hide trims paged the HUD out, so showing it on a busy PC stalled on page faults
    QTimer.singleShot(4000, trim)
    stay_responsive()

    if args.hidden:
        window.setProperty("shown", False)
    if os.environ.get("HUD_DEMO"):  # preview the animations without real agent traffic
        def demo_state(busy, queues, breaker):
            hud._busy, hud._queues, hud._breaker = busy, queues, breaker
            hud.stateChanged.emit()
        steps = [
            (500, lambda: demo_state(["codex"], {}, 0)),
            (1500, lambda: hud.planeSent.emit("agy", "codex")),
            (2700, lambda: demo_state(["codex"], {"codex": 2}, 1)),
            (4000, lambda: hud.planeSent.emit("codex", "claude")),
            (5200, lambda: demo_state(["claude"], {"codex": 1, "claude": 1}, 2)),
            (6500, lambda: demo_state(["claude"], {"claude": 1}, hud._limit)),
            (8000, lambda: demo_drag(0.92, 0.5)),    # fling to the right edge
            (10000, lambda: demo_drag(0.5, 0.04)),   # up to the top: becomes the island
            (12000, lambda: demo_drag(0.05, 0.45)),  # back to the left
        ]

        def demo_drag(fx, fy):
            # place the capsule centre at a fraction of the screen, then let it snap like a real drop
            g = window.screen().availableGeometry()
            dock_cx = window.width() / 2 if window.property("horiz") else 12 + 30
            window.setProperty("dragging", True)
            window.setX(int(g.x() + g.width() * fx - dock_cx))
            window.setY(int(g.y() + g.height() * fy - window.height() / 2))
            window.metaObject().invokeMethod(window, "endDrag")
        for delay, fn in steps:
            QTimer.singleShot(delay, fn)
    if os.environ.get("HUD_DEBUG"):
        report = QTimer()
        report.timeout.connect(lambda: print("HUD", window.isVisible(), window.property("shown"), window.opacity(),
                                             window.geometry(), window.property("side"), "bright" if hud.bgBright else "dark", round(hud._lum, 3), flush=True))
        report.start(1000)
    if os.environ.get("HUD_PERF"):  # smoothness probe: per second, frames + janky gaps (34-500 ms) + slowest glass grab
        perf = {"last": time.perf_counter(), "gaps": []}

        def swapped():
            now = time.perf_counter()
            perf["gaps"].append(now - perf["last"])
            perf["last"] = now
        window.frameSwapped.connect(swapped, Qt.DirectConnection)

        def report_perf():
            g, perf["gaps"] = perf["gaps"], []
            jank = [x for x in g if 0.034 < x < 0.5]
            print(f"PERF frames={len(g)} jank={len(jank)} worst={max(jank, default=0) * 1000:.0f}ms grab={hud._grab_ms:.1f}ms "
                  f"gui={perf['stall'] * 1000:.0f}ms", flush=True)
            hud._grab_ms, perf["stall"] = 0.0, 0.0
        perf_timer = QTimer()
        perf_timer.timeout.connect(report_perf)
        perf_timer.start(1000)
        perf["tick"], perf["stall"] = time.perf_counter(), 0.0

        def gui_tick():  # GUI-thread stall: how late a 10 ms timer fires (render thread keeps swapping while GUI blocks)
            now = time.perf_counter()
            perf["stall"] = max(perf["stall"], now - perf["tick"] - 0.010)
            perf["tick"] = now
        tick_timer = QTimer()
        tick_timer.setTimerType(Qt.PreciseTimer)
        tick_timer.timeout.connect(gui_tick)
        tick_timer.start(10)
        main_id = threading.get_ident()

        def watchdog():  # name the Python line the GUI thread is stuck on (only Python frames are visible)
            import traceback
            while True:
                time.sleep(0.04)
                if time.perf_counter() - perf["tick"] > 0.06:
                    frame = sys._current_frames().get(main_id)
                    where = " < ".join(f"{f.name}:{f.lineno}" for f in reversed(traceback.extract_stack(frame)[-3:])) if frame else "?"
                    print(f"STALL {time.perf_counter():.3f} {(time.perf_counter() - perf['tick']) * 1000:.0f}ms in {where}", flush=True)
                    time.sleep(0.1)
        threading.Thread(target=watchdog, daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
