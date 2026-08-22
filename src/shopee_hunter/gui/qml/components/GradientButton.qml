import QtQuick
import QtQuick.Effects
import Theme

/*!
    The primary action button: accent gradient, a glow that follows hover, and a press
    scale-down. `flat: true` gives the secondary (glass) variant so both live in one
    component and cannot drift apart.
*/
Item {
    id: control

    property bool busy: false
    property bool enabled: true
    property bool flat: false
    property int horizontalPadding: Theme.spacingLg
    property string iconText: ""
    property string text: ""

    signal clicked

    implicitHeight: 40
    implicitWidth: label.implicitWidth + (iconLabel.visible ? iconLabel.width + Theme.spacingSm : 0) + horizontalPadding * 2
    opacity: enabled ? 1.0 : 0.45

    Behavior on opacity {
        NumberAnimation {
            duration: Theme.durFast
        }
    }

    // The glow sits behind and slightly inset, so it reads as light spilling out of the
    // button rather than as a second border.
    Rectangle {
        anchors.centerIn: surface
        color: "transparent"
        height: surface.height + 18
        layer.enabled: true
        opacity: hover.hovered ? 1.0 : 0.0
        radius: Theme.radiusPill
        visible: !control.flat && control.enabled
        width: surface.width + 18

        gradient: Gradient {
            GradientStop {
                color: Theme.accentGlow
                position: 0.0
            }
            GradientStop {
                color: "transparent"
                position: 1.0
            }
        }
        layer.effect: MultiEffect {
            blur: 1.0
            blurEnabled: true
            blurMax: 32
        }
        Behavior on opacity {
            NumberAnimation {
                duration: Theme.durBase
                easing.type: Theme.easeStandard
            }
        }
    }
    Rectangle {
        id: surface

        anchors.fill: parent
        antialiasing: true
        border.color: hover.hovered ? Theme.glassBorderStrong : Theme.glassBorder
        border.width: control.flat ? Theme.borderThin : 0
        color: control.flat ? (hover.hovered ? Theme.glassFillHover : Theme.glassFill) : "transparent"
        radius: Theme.radiusPill
        scale: press.pressed ? 0.965 : (hover.hovered ? 1.02 : 1.0)

        Behavior on scale {
            NumberAnimation {
                duration: Theme.durFast
                easing.type: Theme.easeStandard
            }
        }

        // The accent fill is its own Rectangle rather than a conditional `gradient:`,
        // because QML cannot put an object declaration on the right of a ternary — the
        // primary and flat variants have to differ by visibility, not by expression.
        Rectangle {
            anchors.fill: parent
            antialiasing: true
            radius: parent.radius
            visible: !control.flat

            gradient: Gradient {
                orientation: Gradient.Horizontal

                GradientStop {
                    color: Qt.lighter(Theme.accent, 1.18)
                    position: 0.0
                }
                GradientStop {
                    color: Qt.darker(Theme.accent, 1.12)
                    position: 1.0
                }
            }
        }
        Row {
            anchors.centerIn: parent
            spacing: Theme.spacingSm

            Text {
                id: iconLabel

                anchors.verticalCenter: parent.verticalCenter
                color: control.flat ? Theme.textPrimary : Theme.textOnAccent
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontLg
                text: control.iconText
                visible: control.iconText.length > 0 && !control.busy
            }

            // The busy spinner replaces the icon rather than joining it, so the button's
            // width does not jump the moment a scan starts.
            Item {
                anchors.verticalCenter: parent.verticalCenter
                height: 14
                visible: control.busy
                width: 14

                RotationAnimator on rotation {
                    duration: Theme.durSlow * 2
                    from: 0
                    loops: Animation.Infinite
                    running: control.busy && Theme.effectiveMotion > 0
                    to: 360
                }

                Rectangle {
                    anchors.fill: parent
                    border.color: Theme.glassHighlight
                    border.width: 2
                    color: "transparent"
                    radius: width / 2
                }
                Rectangle {
                    color: control.flat ? Theme.accent : Theme.textOnAccent
                    height: 4
                    radius: Theme.radiusPill
                    transformOrigin: Item.Center
                    width: 4
                    x: parent.width / 2 - 2
                    y: -1
                }
            }
            Text {
                id: label

                anchors.verticalCenter: parent.verticalCenter
                color: control.flat ? Theme.textPrimary : Theme.textOnAccent
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontMd
                font.weight: Font.DemiBold
                text: control.text
            }
        }
    }
    HoverHandler {
        id: hover

        cursorShape: Qt.PointingHandCursor
        enabled: control.enabled
    }
    TapHandler {
        id: press

        enabled: control.enabled

        onTapped: control.clicked()
    }
}
