import QtQuick
import Theme

/*!
    A pill label. `tone` picks the semantic colour so a caller never passes a raw colour and
    the warning/positive vocabulary stays consistent across views.
*/
Rectangle {
    id: badge

    property bool filled: false
    property string text: ""
    property string tone: "neutral"   // neutral | accent | positive | caution | negative | info
    readonly property color toneColor: {
        switch (tone) {
        case "accent":
            return Theme.accent;
        case "positive":
            return Theme.positive;
        case "caution":
            return Theme.caution;
        case "negative":
            return Theme.negative;
        case "info":
            return Theme.info;
        default:
            return Theme.textMuted;
        }
    }

    antialiasing: true
    border.color: Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.35)
    border.width: filled ? 0 : Theme.borderThin
    color: filled ? toneColor : Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.14)
    implicitHeight: 22
    implicitWidth: label.implicitWidth + Theme.spacingMd
    radius: Theme.radiusPill

    Text {
        id: label

        anchors.centerIn: parent
        color: badge.filled ? Theme.textOnAccent : Qt.rgba(badge.toneColor.r, badge.toneColor.g, badge.toneColor.b, 0.95)
        font.capitalization: Font.AllUppercase
        font.family: Theme.fontFamily
        font.letterSpacing: 0.4
        font.pixelSize: Theme.fontXs
        font.weight: Font.DemiBold
        text: badge.text
    }
}
