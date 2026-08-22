import QtQuick
import QtQuick.Controls.Basic
import Theme

/*!
    Text input. Controls.Basic on purpose: the native styles render differently on macOS and
    Windows, and platform-identical rendering is the whole reason the UI is QML (ADR-002).
*/
Item {
    id: field

    property string glyph: "⌕"
    property bool numeric: false
    property string placeholder: ""
    property alias text: input.text

    signal accepted

    implicitHeight: 40
    implicitWidth: 260

    Rectangle {
        anchors.fill: parent
        border.color: input.activeFocus ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55) : Theme.glassBorder
        border.width: Theme.borderThin
        color: input.activeFocus ? Theme.glassFillStrong : Theme.glassFill
        radius: Theme.radiusMd

        Behavior on border.color {
            ColorAnimation {
                duration: Theme.durFast
            }
        }
        Behavior on color {
            ColorAnimation {
                duration: Theme.durFast
            }
        }
    }
    Text {
        id: glyphLabel

        anchors.left: parent.left
        anchors.leftMargin: Theme.spacingMd
        anchors.verticalCenter: parent.verticalCenter
        color: input.activeFocus ? Theme.accent : Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontLg
        text: field.glyph
        visible: field.glyph.length > 0

        Behavior on color {
            ColorAnimation {
                duration: Theme.durFast
            }
        }
    }
    TextField {
        id: input

        anchors.fill: parent
        anchors.leftMargin: glyphLabel.visible ? Theme.spacingXl : Theme.spacingMd
        anchors.rightMargin: Theme.spacingMd
        background: null
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontMd
        inputMethodHints: field.numeric ? Qt.ImhDigitsOnly : Qt.ImhNone
        placeholderText: field.placeholder
        placeholderTextColor: Theme.textMuted
        selectedTextColor: Theme.textPrimary
        selectionColor: Theme.accentSoft
        validator: field.numeric ? intValidator : null
        verticalAlignment: TextInput.AlignVCenter

        onAccepted: field.accepted()
    }
    IntValidator {
        id: intValidator

        bottom: 0
        top: 2000000000
    }
}
