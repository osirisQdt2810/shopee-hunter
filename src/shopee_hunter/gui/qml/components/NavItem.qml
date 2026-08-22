import QtQuick
import Theme

/*!
    One sidebar entry. The selection indicator is a single Rectangle that animates between
    items rather than one per item fading in/out — that is what makes the highlight look like
    it slides.
*/
Item {
    id: item

    property int badgeCount: 0
    property bool current: false
    property string glyph: ""
    property string label: ""

    signal activated

    implicitHeight: 42

    Rectangle {
        anchors.fill: parent
        color: item.current ? Theme.accentSoft : (hover.hovered ? Theme.glassFill : "transparent")
        radius: Theme.radiusMd

        Behavior on color {
            ColorAnimation {
                duration: Theme.durFast
            }
        }
    }
    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.accent
        height: item.current ? parent.height * 0.55 : 0
        radius: 2
        width: 3

        Behavior on height {
            NumberAnimation {
                duration: Theme.durBase
                easing.type: Theme.easeEnter
            }
        }
    }
    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.spacingMd
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacingSm
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spacingSm

        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: item.current ? Theme.accent : Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontLg
            text: item.glyph

            Behavior on color {
                ColorAnimation {
                    duration: Theme.durFast
                }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: item.current ? Theme.textPrimary : Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontMd
            font.weight: item.current ? Font.DemiBold : Font.Normal
            text: item.label

            Behavior on color {
                ColorAnimation {
                    duration: Theme.durFast
                }
            }
        }
    }
    Badge {
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacingSm
        anchors.verticalCenter: parent.verticalCenter
        filled: item.current
        text: item.badgeCount
        tone: "accent"
        visible: item.badgeCount > 0
    }
    HoverHandler {
        id: hover

        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        onTapped: item.activated()
    }
}
