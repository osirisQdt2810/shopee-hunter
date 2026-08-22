import QtQuick
import Theme

/*!
    What the content area shows when there is nothing to show. Deliberately a real component:
    the empty case is most of a new user's first session, and "no deals yet" needs to say
    *why* and what to do next, not just be blank.
*/
Column {
    id: empty

    property string actionText: ""
    property string body: ""
    property string glyph: "◎"
    property string title: ""

    signal actionTriggered

    spacing: Theme.spacingMd
    width: Math.min(parent ? parent.width * 0.7 : 420, 460)

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        color: Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: 52
        opacity: 0.6
        text: empty.glyph

        SequentialAnimation on scale {
            loops: Animation.Infinite
            running: Theme.effectiveMotion > 0

            NumberAnimation {
                duration: Theme.durAmbient / 4
                easing.type: Theme.easeAmbient
                to: 1.06
            }
            NumberAnimation {
                duration: Theme.durAmbient / 4
                easing.type: Theme.easeAmbient
                to: 1.0
            }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontXl
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        text: empty.title
        width: parent.width
        wrapMode: Text.WordWrap
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontMd
        horizontalAlignment: Text.AlignHCenter
        lineHeight: 1.35
        text: empty.body
        width: parent.width
        wrapMode: Text.WordWrap
    }
    GradientButton {
        anchors.horizontalCenter: parent.horizontalCenter
        text: empty.actionText
        visible: empty.actionText.length > 0

        onClicked: empty.actionTriggered()
    }
}
