import QtQuick
import Theme

/*!
    One number with a label, for the header strip. The value counts up on change so a scan
    finishing is visible even when the user is looking at a different part of the window.
*/
GlassPanel {
    id: tile

    property string hint: ""
    property string label: ""
    property color tint: Theme.accent
    property string value: ""

    elevated: false
    implicitHeight: 74
    implicitWidth: 150
    radius: Theme.radiusMd

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.margins: 1
        anchors.top: parent.top
        color: tile.tint
        opacity: 0.85
        radius: Theme.radiusPill
        width: 3
    }
    Column {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacingMd + 4
        anchors.margins: Theme.spacingMd
        spacing: 1

        Text {
            color: Theme.textMuted
            font.capitalization: Font.AllUppercase
            font.family: Theme.fontFamily
            font.letterSpacing: 0.6
            font.pixelSize: Theme.fontXs
            text: tile.label
        }
        Text {
            id: valueLabel

            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontXl
            font.weight: Font.Bold
            text: tile.value

            // A quick dip-and-recover on change reads as "this just updated" without moving
            // the layout. Driven by onTextChanged rather than `Behavior on text`, because a
            // Behavior would have to interpolate the string itself.
            onTextChanged: if (Theme.effectiveMotion > 0)
                pulse.restart()

            SequentialAnimation {
                id: pulse

                NumberAnimation {
                    duration: Theme.durFast
                    property: "opacity"
                    target: valueLabel
                    to: 0.3
                }
                NumberAnimation {
                    duration: Theme.durBase
                    easing.type: Theme.easeStandard
                    property: "opacity"
                    target: valueLabel
                    to: 1.0
                }
            }
        }
        Text {
            color: Theme.textSecondary
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontXs
            text: tile.hint
            visible: tile.hint.length > 0
            width: tile.width - Theme.spacingLg
        }
    }
}
