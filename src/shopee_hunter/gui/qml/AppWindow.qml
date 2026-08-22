import QtQuick
import QtQuick.Window
import Theme
import components
import views

/*!
    The application shell: frameless translucent window, animated aurora, sidebar, header
    strip, and the view stack.

    The window is frameless because the chrome is part of the design (ADR-002); the native
    flags and the OS blur are set once in `gui/window.py` and nothing here touches them.
    Everything visual comes from the Theme singleton.
*/
Window {
    id: root

    // Bound from the context properties app.py installs. `typeof` guards keep the file
    // loadable in a QML-only preview (qml AppWindow.qml) where neither exists, and every
    // use site is still written `bridge ? … : …` for the same reason.
    property var bridge: typeof appBridge !== "undefined" ? appBridge : null
    property int currentView: 0
    property var windowEffects: typeof appWindowEffects !== "undefined" ? appWindowEffects : null

    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    height: 820
    minimumHeight: 660
    minimumWidth: 1040
    title: "Sale Hunter"
    visible: true
    width: 1280

    Component.onCompleted: {
        if (bridge) {
            Theme.accent = bridge.accent;
            Theme.reducedMotion = bridge.reducedMotion;
            Theme.motionScale = bridge.animationScale;
        }
        if (windowEffects)
            Theme.nativeBlur = windowEffects.hasNativeBlur();
    }

    // Rounded outer shape. Clipped here rather than by the OS so the corner radius is the
    // same on both platforms — Windows 11's own rounding is a different radius from macOS's.
    Rectangle {
        id: shell

        anchors.fill: parent
        clip: true
        color: "transparent"
        radius: root.visibility === Window.Maximized ? 0 : Theme.windowRadius

        AuroraBackground {
            // Pause the ambient animation when the window is not on screen: a background
            // window repainting a blurred gradient forever is a laptop-battery bug.
            active: root.visible && root.visibility !== Window.Minimized
            anchors.fill: parent
        }

        // A hairline outer border keeps the window edge visible against a light desktop,
        // where a translucent dark window would otherwise bleed into the wallpaper.
        Rectangle {
            anchors.fill: parent
            border.color: Theme.glassBorder
            border.width: Theme.borderThin
            color: "transparent"
            radius: shell.radius
        }
        Column {
            anchors.fill: parent
            spacing: 0

            TitleBar {
                title: "Sale Hunter" + (root.bridge && root.bridge.demoMode ? "  ·  demo data" : "")
                width: parent.width
                window: root
            }
            Row {
                height: parent.height - Theme.titleBarHeight
                spacing: 0
                width: parent.width

                // ---- sidebar -------------------------------------------------
                Item {
                    id: sidebar

                    height: parent.height
                    width: Theme.sidebarWidth

                    Column {
                        anchors.fill: parent
                        anchors.margins: Theme.spacingMd
                        anchors.topMargin: Theme.spacingSm
                        spacing: Theme.spacingXs

                        Row {
                            bottomPadding: Theme.spacingMd
                            spacing: Theme.spacingSm

                            Rectangle {
                                height: 30
                                radius: Theme.radiusSm
                                width: 30

                                gradient: Gradient {
                                    GradientStop {
                                        color: Qt.lighter(Theme.accent, 1.2)
                                        position: 0.0
                                    }
                                    GradientStop {
                                        color: Theme.auroraD
                                        position: 1.0
                                    }
                                }

                                Text {
                                    anchors.centerIn: parent
                                    color: Theme.textOnAccent
                                    font.pixelSize: Theme.fontLg
                                    font.weight: Font.Bold
                                    text: "◈"
                                }
                            }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: -2

                                Text {
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontLg
                                    font.weight: Font.Bold
                                    text: "Sale Hunter"
                                }
                                Text {
                                    color: Theme.textMuted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontXs
                                    text: root.bridge ? root.bridge.storefront : "shopee.vn"
                                }
                            }
                        }
                        NavItem {
                            badgeCount: root.bridge ? root.bridge.dealCount : 0
                            current: root.currentView === 0
                            glyph: "◎"
                            label: "Deals"
                            width: parent.width

                            onActivated: root.currentView = 0
                        }
                        NavItem {
                            current: root.currentView === 1
                            glyph: "☰"
                            label: "Watches"
                            width: parent.width

                            onActivated: root.currentView = 1
                        }
                        NavItem {
                            current: root.currentView === 2
                            glyph: "⏱"
                            label: "Sale calendar"
                            width: parent.width

                            onActivated: root.currentView = 2
                        }
                        NavItem {
                            current: root.currentView === 3
                            glyph: "⚙"
                            label: "How it works"
                            width: parent.width

                            onActivated: root.currentView = 3
                        }
                        Item {
                            height: parent.height - y - statusCard.height - Theme.spacingMd
                            width: parent.width
                        }

                        // The status card sits at the bottom of the sidebar so the app always
                        // says what it is doing, in every view.
                        GlassPanel {
                            id: statusCard

                            elevated: false
                            height: 88
                            radius: Theme.radiusMd
                            width: parent.width

                            Column {
                                anchors.fill: parent
                                anchors.margins: Theme.spacingMd
                                spacing: 4

                                Row {
                                    spacing: Theme.spacingSm

                                    Rectangle {
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: root.bridge && root.bridge.busy ? Theme.caution : Theme.positive
                                        height: 7
                                        radius: Theme.radiusPill
                                        width: 7

                                        SequentialAnimation on opacity {
                                            loops: Animation.Infinite
                                            running: root.bridge ? root.bridge.busy && Theme.effectiveMotion > 0 : false

                                            NumberAnimation {
                                                duration: Theme.durBase
                                                to: 0.25
                                            }
                                            NumberAnimation {
                                                duration: Theme.durBase
                                                to: 1.0
                                            }
                                        }
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: Theme.textSecondary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSm
                                        font.weight: Font.DemiBold
                                        text: root.bridge && root.bridge.busy ? "Scanning" : "Idle"
                                    }
                                }
                                Text {
                                    color: Theme.textMuted
                                    elide: Text.ElideRight
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontXs
                                    maximumLineCount: 2
                                    text: root.bridge ? root.bridge.status : ""
                                    width: parent.width
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    color: Theme.textMuted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontXs
                                    text: root.bridge ? "last scan " + root.bridge.lastScanText : ""
                                }
                            }
                        }
                    }

                    // Vertical divider instead of a filled sidebar: the aurora should run
                    // behind the whole window, not stop at a panel edge.
                    Rectangle {
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        anchors.top: parent.top
                        color: Theme.glassBorder
                        width: 1
                    }
                }

                // ---- content -------------------------------------------------
                Item {
                    height: parent.height
                    width: parent.width - Theme.sidebarWidth

                    Column {
                        anchors.fill: parent
                        anchors.margins: Theme.spacingLg
                        spacing: Theme.spacingMd

                        // Header strip: the three numbers that matter, plus the campaign
                        // countdown, visible from every view.
                        Row {
                            height: Theme.headerHeight
                            spacing: Theme.spacingSm
                            width: parent.width

                            StatTile {
                                height: parent.height
                                hint: root.bridge && root.bridge.sourceUsed ? "via " + root.bridge.sourceUsed : "no scan yet"
                                label: "verified deals"
                                tint: Theme.positive
                                value: root.bridge ? root.bridge.dealCount : "0"
                            }
                            StatTile {
                                height: parent.height
                                hint: root.bridge ? root.bridge.nextSaleText : ""
                                label: "sale state"
                                tint: root.bridge && root.bridge.tierIsPeak ? Theme.accent : Theme.info
                                value: root.bridge ? root.bridge.tierLabel : ""
                                width: 260
                            }
                            Item {
                                height: 1
                                width: parent.width - 150 - 260 - actions.width - Theme.spacingSm * 3
                            }
                            Row {
                                id: actions

                                anchors.verticalCenter: parent.verticalCenter
                                spacing: Theme.spacingSm

                                GradientButton {
                                    enabled: !(root.bridge && root.bridge.busy)
                                    flat: true
                                    iconText: "⚡"
                                    text: "Flash sale"

                                    onClicked: if (root.bridge)
                                        root.bridge.scanFlashSale()
                                }
                                GradientButton {
                                    busy: root.bridge ? root.bridge.busy : false
                                    iconText: root.bridge && root.bridge.busy ? "✕" : "⟳"
                                    text: root.bridge && root.bridge.busy ? "Cancel" : "Scan now"

                                    onClicked: {
                                        if (!root.bridge)
                                            return;
                                        if (root.bridge.busy)
                                            root.bridge.cancelScan();
                                        else
                                            root.bridge.scanNow();
                                    }
                                }
                            }
                        }

                        // The view stack. Views cross-fade and slide slightly, which reads as
                        // navigation; an instant swap reads as a redraw glitch.
                        Item {
                            id: stack

                            height: parent.height - Theme.headerHeight - Theme.spacingMd
                            width: parent.width

                            Page {
                                pageIndex: 0

                                DealsView {
                                    anchors.fill: parent
                                    bridge: root.bridge
                                }
                            }
                            Page {
                                pageIndex: 1

                                WatchesView {
                                    anchors.fill: parent
                                    bridge: root.bridge
                                }
                            }
                            Page {
                                pageIndex: 2

                                CalendarView {
                                    anchors.fill: parent
                                    bridge: root.bridge
                                }
                            }
                            Page {
                                pageIndex: 3

                                SettingsView {
                                    anchors.fill: parent
                                    bridge: root.bridge
                                }
                            }
                        }
                    }
                }
            }
        }

        // Resize grip. A frameless window has no native one, and a window that cannot be
        // resized feels broken however good it looks.
        Item {
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            height: 18
            width: 18

            Repeater {
                model: 3

                Rectangle {
                    color: Theme.textMuted
                    height: 3
                    opacity: 0.5
                    radius: Theme.radiusPill
                    width: 3
                    x: 12 - index * 4
                    y: 12
                }
            }
            HoverHandler {
                cursorShape: Qt.SizeFDiagCursor
            }
            DragHandler {
                target: null

                onActiveChanged: if (active)
                    root.startSystemResize(Qt.BottomEdge | Qt.RightEdge)
            }
        }
        Toast {
            id: toast

            anchors.bottom: parent.bottom
            anchors.bottomMargin: Theme.spacingXl
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
    Connections {
        function onToast(message, severity) {
            toast.show(message, severity);
        }

        target: root.bridge
    }

    // Keyboard shortcuts, platform-correct modifiers via StandardKey where one exists.
    Shortcut {
        sequences: [StandardKey.Refresh, "Ctrl+R"]

        onActivated: if (root.bridge && !root.bridge.busy)
            root.bridge.scanNow()
    }
    Shortcut {
        sequence: StandardKey.Find

        onActivated: root.currentView = 0
    }
    Shortcut {
        sequence: StandardKey.Quit

        onActivated: root.close()
    }

    component Page: Item {
        readonly property bool active: root.currentView === pageIndex
        property int pageIndex: 0

        // `stackPage` is this Page: an alias so the Translate above can
        // read `active` without walking the parent chain.
        readonly property Item stackPage: this

        anchors.fill: parent
        opacity: active ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.durBase
                easing.type: Theme.easeStandard
            }
        }
        transform: Translate {
            y: stackPage.active ? 0 : 10
        }
    }
}
