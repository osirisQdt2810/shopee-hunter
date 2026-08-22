import QtQuick
import Theme

/*!
    Custom window chrome. The window is frameless (gui/window.py), so drag, close, minimise
    and maximise all live here — and the button ORDER follows the host platform even though
    everything else about the app deliberately does not.

    That is not an inconsistency: colours and motion are the product's identity and should
    match everywhere, but "where is the close button" is muscle memory, and getting it wrong
    makes the app feel broken rather than styled.
*/
Item {
    id: bar

    readonly property bool macStyle: Qt.platform.os === "osx"
    property string title: ""
    property Window window: null

    implicitHeight: Theme.titleBarHeight

    // The drag region excludes the buttons so a click near them cannot start a drag.
    DragHandler {
        target: null

        onActiveChanged: if (active && bar.window)
            bar.window.startSystemMove()
    }
    TapHandler {
        onDoubleTapped: {
            if (!bar.window)
                return;
            bar.window.visibility = bar.window.visibility === Window.Maximized ? Window.Windowed : Window.Maximized;
        }
    }

    // macOS: traffic lights on the left.
    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.spacingMd
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spacingSm
        visible: bar.macStyle

        WindowButton {
            glyph: "✕"
            tint: Theme.trafficClose
            traffic: true

            onTriggered: if (bar.window)
                bar.window.close()
        }
        WindowButton {
            glyph: "−"
            tint: Theme.trafficMinimise
            traffic: true

            onTriggered: if (bar.window)
                bar.window.showMinimized()
        }
        WindowButton {
            glyph: "+"
            tint: Theme.trafficMaximise
            traffic: true

            onTriggered: {
                if (!bar.window)
                    return;
                bar.window.visibility = bar.window.visibility === Window.Maximized ? Window.Windowed : Window.Maximized;
            }
        }
    }
    Text {
        anchors.centerIn: parent
        color: Theme.textMuted
        font.family: Theme.fontFamily
        font.letterSpacing: 0.5
        font.pixelSize: Theme.fontSm
        text: bar.title
    }

    // Windows/Linux: minimise, maximise, close on the right.
    Row {
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacingSm
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        visible: !bar.macStyle

        WindowButton {
            glyph: "─"

            onTriggered: if (bar.window)
                bar.window.showMinimized()
        }
        WindowButton {
            glyph: "□"

            onTriggered: {
                if (!bar.window)
                    return;
                bar.window.visibility = bar.window.visibility === Window.Maximized ? Window.Windowed : Window.Maximized;
            }
        }
        WindowButton {
            glyph: "✕"

            onTriggered: if (bar.window)
                bar.window.close()
        }
    }

    component WindowButton: Item {
        property string glyph: ""
        property color tint: Theme.textMuted
        property bool traffic: false

        signal triggered

        implicitHeight: traffic ? 13 : 26
        implicitWidth: traffic ? 13 : 34

        Rectangle {
            anchors.fill: parent
            color: parent.traffic ? parent.tint : (btnHover.hovered ? Theme.glassFillHover : "transparent")
            radius: parent.traffic ? width / 2 : Theme.radiusSm

            Behavior on color {
                ColorAnimation {
                    duration: Theme.durFast
                }
            }
        }
        Text {
            anchors.centerIn: parent
            color: parent.traffic ? Theme.trafficGlyph : Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: parent.traffic ? 8 : Theme.fontSm
            font.weight: Font.Bold
            text: parent.glyph
            visible: !parent.traffic || btnHover.hovered
        }
        HoverHandler {
            id: btnHover

            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            onTapped: parent.triggered()
        }
    }
}
