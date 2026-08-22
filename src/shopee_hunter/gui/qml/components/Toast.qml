import QtQuick
import Theme

/*!
    Transient message, bottom-centre. One instance in AppWindow; `show()` re-arms it, so a
    burst of messages replaces rather than stacks — stacked toasts cover the content the user
    is trying to read.
*/
Item {
    id: toast

    property int lifetimeMs: 4200
    property string message: ""
    property string severity: "info"
    readonly property color toneColor: {
        switch (severity) {
        case "warn":
            return Theme.caution;
        case "error":
            return Theme.negative;
        default:
            return Theme.info;
        }
    }

    function show(text, kind) {
        toast.message = text;
        toast.severity = kind || "info";
        enter.restart();
        life.restart();
    }

    height: 48
    opacity: 0
    visible: opacity > 0.01
    width: Math.min(parent ? parent.width - Theme.spacingXl * 2 : 480, Math.max(280, label.implicitWidth + Theme.spacingXl * 2))

    transform: Translate {
        id: slide

        y: 24
    }

    GlassPanel {
        anchors.fill: parent
        fill: Theme.glassFillStrong
        radius: Theme.radiusPill

        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spacingLg
            anchors.verticalCenter: parent.verticalCenter
            color: toast.toneColor
            height: 8
            radius: 4
            width: 8

            // A pulse rather than a static dot: it draws the eye to a message that appeared
            // while the user was looking elsewhere.
            SequentialAnimation on scale {
                loops: Animation.Infinite
                running: toast.visible && Theme.effectiveMotion > 0

                NumberAnimation {
                    duration: Theme.durSlow
                    easing.type: Theme.easeAmbient
                    to: 1.6
                }
                NumberAnimation {
                    duration: Theme.durSlow
                    easing.type: Theme.easeAmbient
                    to: 1.0
                }
            }
        }
        Text {
            id: label

            anchors.left: parent.left
            anchors.leftMargin: Theme.spacingXl + Theme.spacingSm
            anchors.right: parent.right
            anchors.rightMargin: Theme.spacingLg
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textPrimary
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontMd
            text: toast.message
            wrapMode: Text.NoWrap
        }
    }
    ParallelAnimation {
        id: enter

        NumberAnimation {
            duration: Theme.durBase
            property: "opacity"
            target: toast
            to: 1
        }
        NumberAnimation {
            duration: Theme.durBase
            easing.type: Theme.easeEnter
            property: "y"
            target: slide
            to: 0
        }
    }
    SequentialAnimation {
        id: life

        PauseAnimation {
            duration: toast.lifetimeMs
        }
        ParallelAnimation {
            NumberAnimation {
                duration: Theme.durBase
                property: "opacity"
                target: toast
                to: 0
            }
            NumberAnimation {
                duration: Theme.durBase
                easing.type: Theme.easeExit
                property: "y"
                target: slide
                to: 16
            }
        }
    }
    TapHandler {
        onTapped: life.complete()
    }
}
