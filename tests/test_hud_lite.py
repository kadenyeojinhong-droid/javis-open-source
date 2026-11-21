"""Checks for the lite capsule: it loads, has no cards or settings, and approve.py behaves."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_capsule_qml_has_no_cards_or_settings():
    qml = (ROOT / "ui" / "lite" / "Capsule.qml").read_text(encoding="utf-8")
    for gone in ("SettingsCard", "IntentCard", "ApprovalBar", "Switch {", "TextField", "import QtQuick.Controls"):
        assert gone not in qml
    # the only endless animation is the working ring, and it only runs while busy
    assert qml.count("Animation.Infinite") == 1
    assert "running: av.busy" in qml


def test_capsule_qml_loads():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtCore import QObject, Property, Signal, QUrl, QPoint

    class FakeHud(QObject):
        stateChanged = Signal(); planeSent = Signal(str, str); glassChanged = Signal(); attention = Signal(); brightChanged = Signal()
        bgBright = Property(bool, lambda s: False, notify=brightChanged)
        glassRect = Property("QVariantMap", lambda s: {"x": 0, "y": 0, "w": 0, "h": 0}, notify=glassChanged)
        agents = Property("QVariantList", lambda s: [], notify=stateChanged)
        busy = Property("QVariantList", lambda s: ["codex"], notify=stateChanged)
        standins = Property("QVariantList", lambda s: ["codex"], notify=stateChanged)
        models = Property("QVariantMap", lambda s: {"codex": {"model": "deepseek-r1-local", "purpose": "监管审查 T1"}}, notify=stateChanged)
        queues = Property("QVariantMap", lambda s: {"codex": 2}, notify=stateChanged)
        breaker = Property(int, lambda s: 3, notify=stateChanged)
        limit = Property(int, lambda s: 10, notify=stateChanged)
        idleSeconds = Property(int, lambda s: 0, notify=stateChanged)
        glassRev = Property(int, lambda s: 0, notify=glassChanged)

        from PySide6.QtCore import Slot

        @Slot("QVariantList")
        def setInputRegion(self, rects): self.rects = rects

        @Slot(result="QVariantMap")
        def loadPos(self): return {}

        @Slot(str, int)
        def savePos(self, side, offset): pass

        @Slot(int, int, int, int, int)
        def captureGlass(self, *a): pass

        @Slot(result=QPoint)
        def cursorPos(self): return QPoint(0, 0)

        @Slot(int, int)
        def moveWindow(self, x, y): self.moved = (x, y)

    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    hud = FakeHud()
    engine.rootContext().setContextProperty("hud", hud)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "ui" / "lite" / "Capsule.qml")))
    win = comp.create()
    assert win is not None, comp.errorString()
    assert win.property("side") == "left"
    assert hud.rects and hud.rects[0]["w"] > 0   # input region is set, so the rest of the window is click-through
    app.processEvents()
    assert win.property("snapT") == 0
    win.setProperty("snapFrom", QPoint(0, 0)); win.setProperty("snapTo", QPoint(100, 40)); win.setProperty("snapT", 0.5)
    assert hud.moved == (50, 20)   # snap drives one atomic move per tick
    hud.stateChanged.emit()
    app.processEvents()
    assert win.property("tipId") == "codex"   # a model starting work pops its tooltip without hovering
    assert not [w for w in warnings if "Capsule.qml" in w], warnings
    win.deleteLater()


def test_gdi_bgra_buffer_becomes_owned_qimage():
    from hud_lite import _bgra_to_image
    from PySide6.QtGui import QColor

    image = _bgra_to_image(bytes((0, 0, 255, 255, 0, 255, 0, 255)), 2, 1)
    assert (image.width(), image.height()) == (2, 1)
    assert QColor(image.pixel(0, 0)).name() == "#ff0000"
    assert QColor(image.pixel(1, 0)).name() == "#00ff00"


def test_approve_cli_without_server(capsys, monkeypatch):
    import approve
    monkeypatch.setattr(approve, "API", "http://127.0.0.1:1")
    assert approve.main([]) == 1
    assert "not running" in capsys.readouterr().out


def test_approve_rejects_bad_answer(monkeypatch):
    import approve
    monkeypatch.setattr(approve, "call", lambda path, body=None: {"approvals": [{"id": "abc123", "action": "merge"}]})
    assert approve.main(["abc", "maybe"]) == 2
    assert approve.main(["zzz", "no"]) == 1
