// Javis HUD (lite): glass capsule + four agents + activity animations. Visual style: macOS-like frosted glass.
import QtQuick
import QtQuick.Window
import QtQuick.Shapes
import QtQuick.Effects

Window {
    id: root
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
    visible: true
    title: "Javis HUD"

    // ---------- layout model ----------
    property string side: "left"
    readonly property bool horiz: side === "top" || side === "bottom"
    readonly property int gap: 12          // capsule to screen edge
    readonly property int avatar: 40
    readonly property int dockShort: 60
    readonly property int dockLong: 10 + 18 + 8 + 3 * avatar + 2 * 10 + 10
    readonly property int inner: 170       // room toward the screen centre for planes, envelopes, pill, tooltip
    readonly property int along: 46        // room along the edge at both ends
    // one fixed square for every side: changing side never resizes the window (a resize rebuilds the D3D swap chain = hitch)
    readonly property int box: Math.max(dockLong + 2 * along, gap + dockShort + inner)
    width: box
    height: box
    // unit vector from the screen edge toward the centre: where the "open" side is
    readonly property point outward: side === "left" ? Qt.point(1, 0) : side === "right" ? Qt.point(-1, 0)
                                    : side === "top" ? Qt.point(0, 1) : Qt.point(0, -1)

    // ---------- state ----------
    property bool shown: true
    property bool dragging: false
    property bool flying: false
    property real lastActivity: Date.now()
    property string hoverId: ""
    readonly property var colors: ({ claude: "#FF9F0A", agy: "#64D2FF", codex: "#30D158", deepseek: "#4D6BFE" })
    readonly property var icons: ({
        claude: "M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4",
        agy:    "M12 3c.6 4.6 4.4 8.4 9 9-4.6.6-8.4 4.4-9 9-.6-4.6-4.4-8.4-9-9 4.6-.6 8.4-4.4 9-9Z",
        codex:  "M12 3 19.8 7.5v9L12 21l-7.8-4.5v-9Z M9.5 10l2.5 2-2.5 2 M13 15h2.5",
        deepseek: "M3 13c0-4 3.5-7 8-7 3.6 0 6.4 1.9 7.5 4.6L21 9l-.6 3.4c.4 3.9-3.4 7.6-9.4 7.6C6.4 20 3 17 3 13Z M8 11.5h.01 M14 15.5c-1.5 1-3.5 1-5 0"
    })
    // a slot whose agent is out (quota / not installed) is filled by the DeepSeek stand-in: icon + colour swap
    function isStandin(id) { return (hud.standins || []).indexOf(id) >= 0 }
    function agentColor(id) { if (isStandin(id)) return colors.deepseek; var a = hud.agents.find(function (x) { return x.id === id }); return a && a.color ? a.color : colors[id] }
    function agentName(id) { var a = hud.agents.find(function (x) { return x.id === id }); var n = a ? a.name : id; return isStandin(id) ? "DeepSeek（替 " + n + "）" : n }
    function isBusy(id) { return hud.busy.indexOf(id) >= 0 }
    // which model is working in a slot right now (stand-in coding, harness review); ring colour names the model family
    function modelOf(id) { var m = (hud.models || {})[id]; return m ? m : null }
    function ringColor(id) {
        var m = modelOf(id)
        if (!m) return agentColor(id)
        if (m.model.indexOf("local") >= 0) return "#BF5AF2"      // local Ollama: purple
        if (m.model.indexOf("deepseek") >= 0) return colors.deepseek
        if (m.model.indexOf("gemma") >= 0 || m.model.indexOf("gemini") >= 0) return "#5AC8FA"
        return agentColor(id)
    }
    // a model starting work pops its tooltip for 3 s, so you see "who is doing what" without hovering
    property string flashId: ""
    readonly property string tipId: hoverId !== "" ? hoverId : flashId
    property var seenModels: ({})
    Timer { id: flashOff; interval: 3000; onTriggered: root.flashId = "" }
    Connections {
        target: hud
        function onStateChanged() {
            var now = hud.models || {}, before = root.seenModels
            for (var id in now)
                if (!before[id] || before[id].model !== now[id].model || before[id].purpose !== now[id].purpose) {
                    root.flashId = id; flashOff.restart(); break
                }
            root.seenModels = now
        }
    }
    function queueOf(id) { return hud.queues[id] || 0 }
    function touch() { lastActivity = Date.now() }

    // ---------- show / hide (fade, then stop rendering entirely) ----------
    // no auto-hide: once shown it stays on the desktop until the hotkey (or a second launch) hides it
    function toggleShown() { shown = !shown; if (shown) touch() }
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    onOpacityChanged: if (opacity === 0 && !shown) root.visible = false
    onShownChanged: if (shown) { root.visible = true; raise(); refreshGlassSoon.restart() }
    Connections { target: hud; function onAttention() { root.shown = true } }


    // ---------- capsule geometry inside the window ----------
    Item {
        id: dock
        x: root.side === "left" ? root.gap : root.side === "right" ? root.width - root.gap - width : root.along
        y: root.side === "top" ? root.gap : root.side === "bottom" ? root.height - root.gap - height : root.along
        width: root.horiz ? root.dockLong : root.dockShort
        height: root.horiz ? root.dockShort : root.dockLong
        readonly property real radius: Math.min(width, height) / 2
        // show: grows out of its screen edge with a small spring; hide: tucks back in
        transformOrigin: root.side === "left" ? Item.Left : root.side === "right" ? Item.Right : root.side === "top" ? Item.Top : Item.Bottom
        scale: root.shown ? 1 : 0.88
        Behavior on scale { NumberAnimation { duration: root.shown ? 300 : 180; easing.type: root.shown ? Easing.OutBack : Easing.InCubic; easing.overshoot: 1.3 } }

        // soft, wide shadow (GPU, analytic: no texture, no blur pass)
        RectangularShadow {
            anchors.fill: parent; radius: dock.radius
            offset.y: 4; blur: 22; spread: -2
            color: hud.bgBright ? "#40000000" : "#66000000"
            Behavior on color { ColorAnimation { duration: 450; easing.type: Easing.InOutCubic } }
        }
        // frosted glass, done on the GPU: Python hands over a raw (padded) snapshot of the desktop behind; MultiEffect blurs,
        // lifts saturation a little (vibrancy) and clips it to the capsule. Two layers: a new snapshot loads off the GUI
        // thread into the back layer, then fades in over the old one (which stays opaque, so the glass never dips or flashes).
        component GlassLayer: Item {
            id: layerItem
            property var r: ({ x: 0, y: 0, w: 0, h: 0 })
            property point origin   // window coords of this layer's top-left (inline components cannot see outer ids)
            property alias source: exact.source
            readonly property bool ready: exact.status === Image.Ready
            anchors.fill: parent; opacity: 0
            // stretched copy underneath: where the grab was clamped at the screen edge, the blur samples these colours
            // instead of transparent pixels (no dark rim on the screen-side edge)
            Image { anchors.fill: parent; source: exact.source; asynchronous: true; cache: false; smooth: true }
            Image { id: exact; asynchronous: true; cache: false; smooth: true
                    x: layerItem.r.x - layerItem.origin.x; y: layerItem.r.y - layerItem.origin.y; width: layerItem.r.w; height: layerItem.r.h }
        }
        Item {
            id: glass
            readonly property int pad: 24
            x: -pad; y: -pad; width: dock.width + 2 * pad; height: dock.height + 2 * pad
            visible: false
            property Item pending: null
            function load(rev) {
                pending = glassA.z < glassB.z ? glassA : glassB
                pending.r = hud.glassRect
                pending.source = "image://glass/" + rev
            }
            function reveal(layer) {
                if (layer !== pending || !layer.ready) return
                var old = layer === glassA ? glassB : glassA
                layer.z = 1; old.z = 0; layer.opacity = 0
                glassFade.target = layer; glassFade.restart()
            }
            GlassLayer { id: glassA; origin: Qt.point(dock.x - glass.pad, dock.y - glass.pad); onReadyChanged: glass.reveal(glassA) }
            GlassLayer { id: glassB; origin: Qt.point(dock.x - glass.pad, dock.y - glass.pad); onReadyChanged: glass.reveal(glassB) }
            // slow dissolve when the desktop changed under a resting capsule; near-instant while it follows a drag
            NumberAnimation { id: glassFade; property: "opacity"; from: 0; to: 1; duration: root.dragging ? 70 : 420; easing.type: Easing.InOutQuad }
            Connections { target: hud; function onGlassChanged() { glass.load(hud.glassRev) } }
        }
        Item {   // capsule-shaped mask for the effect
            id: glassMask
            x: glass.x; y: glass.y; width: glass.width; height: glass.height
            visible: false; layer.enabled: true
            Rectangle { x: glass.pad; y: glass.pad; width: dock.width; height: dock.height; radius: dock.radius; antialiasing: true }
        }
        MultiEffect {
            x: glass.x; y: glass.y; width: glass.width; height: glass.height
            source: glass
            autoPaddingEnabled: false
            blurEnabled: true; blur: 1.0; blurMax: 40; blurMultiplier: 0.4
            saturation: 0.35
            maskEnabled: true; maskSource: glassMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0
        }
        // tint, sheen and hairline edge (prototype: white 22%, sheen, .5px edge); faded under the dark glass
        Rectangle {
            anchors.fill: parent; radius: dock.radius
            opacity: hud.bgBright ? 0.2 : 1
            Behavior on opacity { NumberAnimation { duration: 450; easing.type: Easing.InOutCubic } }
            gradient: Gradient {
                orientation: root.horiz ? Gradient.Vertical : Gradient.Horizontal
                GradientStop { position: 0.0; color: "#5cffffff" }
                GradientStop { position: 0.45; color: "#3affffff" }
                GradientStop { position: 1.0; color: "#30ffffff" }
            }
            border.width: 1; border.color: "#73ffffff"
        }
        // light from above: soft top sheen + 1 px inner rim, the "lit edge" that makes glass read as glass
        Rectangle {
            anchors.fill: parent; radius: dock.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: hud.bgBright ? "#1fffffff" : "#33ffffff" }
                GradientStop { position: 0.32; color: "#00ffffff" }
            }
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: 1; radius: dock.radius - 1
            color: "transparent"; border.width: 1; border.color: "#14ffffff"
        }
        // dark frosted glass over bright backgrounds: same calm colour on every edge, also while dragging
        Rectangle {
            anchors.fill: parent; radius: dock.radius
            color: "#d01c1c1e"; border.width: 1; border.color: "#38ffffff"
            opacity: hud.bgBright ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 450; easing.type: Easing.InOutCubic } }
        }

        // drag + click surface (whole capsule)
        MouseArea {
            id: drag
            anchors.fill: parent
            hoverEnabled: true
            property point pressGlobal
            property point pressWin
            cursorShape: root.dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            onEntered: root.touch()
            onPressed: function (m) {
                snapAnim.stop()
                pressGlobal = hud.cursorPos(); pressWin = Qt.point(root.x, root.y); root.touch()
            }
            onPositionChanged: function (m) {
                if (!pressed) return
                var g = hud.cursorPos(), dx = g.x - pressGlobal.x, dy = g.y - pressGlobal.y
                if (!root.dragging && Math.abs(dx) + Math.abs(dy) < 6) return
                root.dragging = true
                root.dragTo = Qt.point(pressWin.x + dx, pressWin.y + dy)   // applied once per vsync by dragFrame
            }
            onReleased: root.endDrag()
            onCanceled: root.endDrag()
        }

        // content: handle + four agents
        Grid {
            anchors.centerIn: parent
            columns: root.horiz ? 5 : 1
            rows: root.horiz ? 1 : 5
            spacing: 10
            Item {   // grip
                width: root.horiz ? 18 : root.avatar; height: root.horiz ? root.avatar : 18
                Rectangle {
                    anchors.centerIn: parent; radius: 2; color: "#ffffff"; opacity: 0.55
                    width: root.horiz ? 4 : 18; height: root.horiz ? 18 : 4
                }
            }
            Repeater {
                model: ["claude", "agy", "codex", "deepseek"]
                delegate: Item {
                    id: av
                    required property string modelData
                    readonly property bool busy: root.isBusy(modelData)
                    readonly property bool sub: root.isStandin(modelData)
                    width: root.avatar; height: root.avatar
                    scale: hover.hovered ? 1.08 : 1
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                    HoverHandler { id: hover; onHoveredChanged: { root.hoverId = hovered ? av.modelData : (root.hoverId === av.modelData ? "" : root.hoverId); root.touch() } }

                    Rectangle {
                        anchors.fill: parent; radius: width / 2; border.width: 1
                        color: av.sub ? "#384D6BFE" : "#40ffffff"   // faint DeepSeek-blue wash while standing in
                        border.color: av.sub ? "#664D6BFE" : "#33ffffff"
                        Behavior on color { ColorAnimation { duration: 520; easing.type: Easing.InOutCubic } }
                        Behavior on border.color { ColorAnimation { duration: 520; easing.type: Easing.InOutCubic } }
                    }
                    Repeater {   // SF-Symbols-style replace: outgoing glyph shrinks + fades, incoming grows in from 60 %
                        model: [av.modelData, "deepseek"]
                        delegate: Shape {
                            required property string modelData
                            required property int index
                            readonly property bool lit: (index === 1) === av.sub
                            anchors.centerIn: parent; width: 24; height: 24
                            opacity: lit ? 1 : 0
                            scale: (lit ? 1 : 0.6) * 20 / 24
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }
                            Behavior on scale { NumberAnimation { duration: 560; easing.type: Easing.OutQuint } }
                            preferredRendererType: Shape.CurveRenderer
                            ShapePath {
                                strokeColor: "#ffffff"; strokeWidth: 1.9; fillColor: "transparent"
                                capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                                PathSvg { path: root.icons[modelData] }
                            }
                        }
                    }
                    Rectangle {   // status dot
                        width: 10; height: 10; radius: 5
                        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 1
                        color: av.busy ? root.agentColor(av.modelData) : "#8e8e93"
                        Behavior on color { ColorAnimation { duration: 520; easing.type: Easing.InOutCubic } }
                        border.width: 1.5; border.color: "#ffffff"
                    }
                    Shape {   // working ring: a lit arc that turns only while busy
                        id: ring
                        anchors.centerIn: parent; width: 50; height: 50
                        visible: av.busy
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: root.ringColor(av.modelData)
                            Behavior on strokeColor { ColorAnimation { duration: 520; easing.type: Easing.InOutCubic } }
                            strokeWidth: 2.6; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            PathAngleArc { centerX: 25; centerY: 25; radiusX: 23; radiusY: 23; startAngle: -90; sweepAngle: 115 }
                        }
                        RotationAnimator on rotation { from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: av.busy && root.visible }
                    }
                }
            }
        }
    }

    // ---------- "连续来回 N" pill, outside the capsule on the open side ----------
    Rectangle {
        id: pill
        visible: hud.breaker > 0
        readonly property bool full: hud.breaker >= hud.limit
        height: 24; radius: 12; width: pillText.implicitWidth + 20
        color: full ? "#FF453A" : "#111113"
        x: root.horiz ? dock.x + dock.width / 2 - width / 2 : (root.side === "left" ? dock.x + dock.width + 10 : dock.x - 10 - width)
        y: root.horiz ? (root.side === "top" ? dock.y + dock.height + 10 : dock.y - 10 - height) : dock.y - 4
        Text {
            id: pillText; anchors.centerIn: parent; color: "white"; font.pixelSize: 12; font.weight: Font.DemiBold
            text: pill.full ? "连续来回 " + hud.breaker + " · 已自动暂停" : "连续来回 " + hud.breaker
        }
        transform: Translate { id: shakeShift }
        onFullChanged: if (full) shake.restart()
        SequentialAnimation {
            id: shake
            NumberAnimation { target: shakeShift; property: "x"; to: -4; duration: 70 }
            NumberAnimation { target: shakeShift; property: "x"; to: 4; duration: 90 }
            NumberAnimation { target: shakeShift; property: "x"; to: 0; duration: 70 }
        }
    }

    // ---------- hover label "名字 · 正在工作/空闲" ----------
    Rectangle {
        id: tip
        visible: root.tipId !== "" && !root.dragging
        readonly property var target: root.tipId === "" ? null : avatarCenter(root.tipId)
        height: 26; radius: 9; width: tipText.implicitWidth + 18
        color: "#e6111113"
        x: target ? (root.horiz ? target.x - width / 2 : (root.side === "left" ? target.x + 30 : target.x - 30 - width)) : 0
        y: target ? (root.horiz ? (root.side === "top" ? target.y + 30 : target.y - 30 - height) : target.y - height / 2) : 0
        Text {
            id: tipText; anchors.centerIn: parent; color: "white"; font.pixelSize: 12
            text: root.tipId === "" ? "" : root.modelOf(root.tipId)
                  ? root.agentName(root.tipId) + " · " + root.modelOf(root.tipId).model + " · " + root.modelOf(root.tipId).purpose
                  : root.agentName(root.tipId) + " · " + (root.isBusy(root.tipId) ? "正在工作" : "空闲")
        }
    }

    // ---------- envelopes waiting beside an agent ----------
    function avatarCenter(id) {
        var i = ["claude", "agy", "codex", "deepseek"].indexOf(id)
        var along = 10 + 18 + 10 + i * (avatar + 10) + avatar / 2
        return root.horiz ? Qt.point(dock.x + along, dock.y + dock.height / 2)
                          : Qt.point(dock.x + dock.width / 2, dock.y + along)
    }
    Repeater {
        model: ["claude", "agy", "codex", "deepseek"]
        delegate: Item {
            required property string modelData
            readonly property point c: root.avatarCenter(modelData)
            Repeater {
                model: Math.min(root.queueOf(parent.modelData), 3)
                delegate: Shape {
                    required property int index
                    width: 20; height: 16
                    x: parent.c.x + root.outward.x * 38 - 10 + index * 4
                    y: parent.c.y + root.outward.y * 38 - 8 - index * 4
                    scale: 0
                    Component.onCompleted: scale = 1
                    Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutBack } }
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: "white"; strokeWidth: 1.4; fillColor: "#33000000"; joinStyle: ShapePath.RoundJoin
                        PathSvg { path: "M3.5 1h13a2.5 2.5 0 0 1 2.5 2.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 1 12.5v-9A2.5 2.5 0 0 1 3.5 1Z M1.8 2.2l8.2 6.3 8.2-6.3" }
                    }
                }
            }
        }
    }

    // ---------- paper plane: loops out on a dashed arc, then everything disappears ----------
    Connections {
        target: hud
        function onPlaneSent(from, to) { root.fly(from, to) }
    }
    function fly(from, to) {
        var ids = ["claude", "agy", "codex", "deepseek"]
        var a = avatarCenter(ids.indexOf(from) >= 0 ? from : (to === "codex" ? "agy" : "codex")), b = avatarCenter(to)
        var o = outward, reach = 90 + Math.abs((b.x - a.x) + (b.y - a.y)) * 0.35
        var s = Qt.point(a.x + o.x * 26, a.y + o.y * 26), e = Qt.point(b.x + o.x * 26, b.y + o.y * 26)
        trailPath.startX = s.x; trailPath.startY = s.y
        trailCurve.x = e.x; trailCurve.y = e.y
        trailCurve.control1X = s.x + o.x * reach - o.y * 30; trailCurve.control1Y = s.y + o.y * reach - o.x * 30
        trailCurve.control2X = e.x + o.x * reach + o.y * 30; trailCurve.control2Y = e.y + o.y * reach + o.x * 30
        planePath.startX = s.x; planePath.startY = s.y
        planeCurve.x = e.x; planeCurve.y = e.y
        planeCurve.control1X = trailCurve.control1X; planeCurve.control1Y = trailCurve.control1Y
        planeCurve.control2X = trailCurve.control2X; planeCurve.control2Y = trailCurve.control2Y
        root.flying = true
        flight.restart()
    }
    Shape {
        id: trail
        anchors.fill: parent
        opacity: 0
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            id: trailPath
            strokeColor: "#b3ffffff"; strokeWidth: 1.4; fillColor: "transparent"
            strokeStyle: ShapePath.DashLine; dashPattern: [1.2, 4]; capStyle: ShapePath.RoundCap
            PathCubic { id: trailCurve }
        }
    }
    Shape {
        id: plane
        width: 16; height: 16; opacity: 0
        preferredRendererType: Shape.CurveRenderer
        ShapePath { fillColor: "white"; strokeColor: "transparent"; PathSvg { path: "M2 11 22 3l-6 18-4-7-7-1Z" } }
        transform: Scale { xScale: 16 / 24; yScale: 16 / 24 }
    }
    SequentialAnimation {
        id: flight
        ParallelAnimation {
            NumberAnimation { target: trail; property: "opacity"; from: 0; to: 1; duration: 200 }
            NumberAnimation { target: plane; property: "opacity"; from: 0; to: 1; duration: 120 }
            PathAnimation {
                target: plane; duration: 1100; easing.type: Easing.InOutQuad
                orientation: PathAnimation.RightFirst; anchorPoint: Qt.point(8, 8)
                path: Path { id: planePath; PathCubic { id: planeCurve } }
            }
        }
        ParallelAnimation {
            NumberAnimation { target: plane; property: "opacity"; to: 0; duration: 150 }
            NumberAnimation { target: trail; property: "opacity"; to: 0; duration: 900 }
        }
        ScriptAction { script: root.flying = false }
    }

    // ---------- docking ----------
    readonly property rect avail: Qt.rect(Screen.virtualX, Screen.virtualY, Screen.desktopAvailableWidth, Screen.desktopAvailableHeight)
    function placeFor(s, offset) {
        // window position for a side; offset = capsule centre along that edge (screen coords)
        var a = avail, w = box, h = box
        if (s === "left")   return Qt.point(a.x, Math.max(a.y, Math.min(a.y + a.height - h, offset - h / 2)))
        if (s === "right")  return Qt.point(a.x + a.width - w, Math.max(a.y, Math.min(a.y + a.height - h, offset - h / 2)))
        if (s === "top")    return Qt.point(a.x + (a.width - w) / 2, a.y)
        return Qt.point(a.x + (a.width - w) / 2, a.y + a.height - h)
    }
    function endDrag() {
        if (!dragging) return
        endDragFlush()   // land exactly where the cursor let go before measuring the nearest edge
        dragging = false
        var cx = root.x + dock.x + dock.width / 2, cy = root.y + dock.y + dock.height / 2, a = avail
        var d = { left: cx - a.x, right: a.x + a.width - cx, top: cy - a.y, bottom: a.y + a.height - cy }
        var next = Object.keys(d).reduce(function (p, q) { return d[q] < d[p] ? q : p })
        if (next !== side) {
            side = next   // window resizes; keep the capsule centre where it was before springing to the edge
            hud.moveWindow(Math.round(cx - (dock.x + dock.width / 2)), Math.round(cy - (dock.y + dock.height / 2)))
        }
        var offset = horiz ? cx : cy
        var p = placeFor(side, offset)
        snapFrom = Qt.point(root.x, root.y); snapTo = p
        snapAnim.restart()
        hud.savePos(side, Math.round(offset))
    }
    // drag: mouse events arrive at 125-1000 Hz; move the window at most once per frame, always to the latest point
    property point dragTo
    FrameAnimation {
        id: dragFrame
        running: root.dragging
        onTriggered: hud.moveWindow(Math.round(root.dragTo.x), Math.round(root.dragTo.y))
    }
    function endDragFlush() { if (root.dragging) hud.moveWindow(Math.round(root.dragTo.x), Math.round(root.dragTo.y)) }
    // snap to the edge: one progress value drives an atomic x+y move, eased like an iOS spring (soft, tiny overshoot)
    property point snapFrom
    property point snapTo
    property real snapT: 0
    onSnapTChanged: hud.moveWindow(Math.round(snapFrom.x + (snapTo.x - snapFrom.x) * snapT),
                                   Math.round(snapFrom.y + (snapTo.y - snapFrom.y) * snapT))
    NumberAnimation {
        id: snapAnim
        target: root; property: "snapT"; from: 0; to: 1
        duration: 420; easing.type: Easing.OutBack; easing.overshoot: 0.9
        onFinished: refreshGlassSoon.restart()
    }

    // ---------- glass refresh ----------
    function captureGlass() {
        if (!root.visible || root.dragging || snapAnim.running) return
        hud.captureGlass(dock.x, dock.y, dock.width, dock.height, glass.pad)
    }
    Timer { id: refreshGlassSoon; interval: 150; onTriggered: root.captureGlass() }
    // live glass while dragging (~14 fps of 8 ms grabs); Python backs off on its own if grabs get slow
    Timer { interval: 70; repeat: true; running: root.dragging
            onTriggered: hud.captureGlass(dock.x, dock.y, dock.width, dock.height, glass.pad) }
    Timer { interval: 2000; repeat: true; running: root.visible && root.shown; onTriggered: root.captureGlass() }

    // ---------- input region: only what is drawn takes the mouse; the rest is the desktop's ----------
    function updateMask() {
        if (flying) { hud.setInputRegion([{ x: 0, y: 0, w: width, h: height }]); return }
        var r = [{ x: dock.x - 6, y: dock.y - 6, w: dock.width + 12, h: dock.height + 12 }]
        if (pill.visible) r.push({ x: pill.x - 6, y: pill.y - 6, w: pill.width + 12, h: pill.height + 12 })
        if (tip.visible) r.push({ x: tip.x - 2, y: tip.y - 2, w: tip.width + 4, h: tip.height + 4 })
        var anyQueue = ["claude", "agy", "codex", "deepseek"].some(function (id) { return root.queueOf(id) > 0 })
        if (anyQueue) r.push(horiz ? { x: dock.x, y: side === "top" ? dock.y + dock.height : dock.y - 60, w: dock.width, h: 60 }
                                   : { x: side === "left" ? dock.x + dock.width : dock.x - 60, y: dock.y, w: 60, h: dock.height })
        hud.setInputRegion(r)
    }
    // deferred: lets dependent bindings (dock.x/y after a side change) settle first, and folds bursts into one setMask
    // (the mask also clips drawing, so a stale one makes the capsule vanish)
    function maskSoon() { Qt.callLater(root.updateMask) }
    onFlyingChanged: maskSoon()
    onSideChanged: maskSoon()
    onWidthChanged: maskSoon()
    onHeightChanged: maskSoon()
    Connections { target: pill; function onVisibleChanged() { root.maskSoon() } function onWidthChanged() { root.maskSoon() } }
    Connections { target: tip; function onVisibleChanged() { root.maskSoon() } function onWidthChanged() { root.maskSoon() } }
    Connections { target: hud; function onStateChanged() { root.maskSoon() } }

    Component.onCompleted: {
        var saved = hud.loadPos()
        side = saved.side || "left"
        var p = placeFor(side, saved.offset || (avail.y + avail.height / 2))
        root.x = p.x; root.y = p.y
        updateMask()
        refreshGlassSoon.restart()
    }
}
