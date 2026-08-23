import QtQuick
import Theme
import components

/*!
    The sale calendar, visible. It explains the app's own behaviour: why it is scanning every
    5 minutes today and every 6 hours next Tuesday (ADR-006).

    Data comes from the bridge as pre-formatted rows; the tiers and dates are computed in
    `core/sale_calendar.py`, never here.
*/
Item {
    id: view

    property var bridge: null

    Column {
        anchors.fill: parent
        spacing: Theme.spacingLg

        // ---- the hero countdown ---------------------------------------------
        GlassPanel {
            fill: Theme.glassFillStrong
            height: 168
            width: parent.width

            // A tier-coloured wash so a mega-sale day is unmistakable at a glance.
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: parent.radius - 1

                gradient: Gradient {
                    orientation: Gradient.Horizontal

                    GradientStop {
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.tierGlow(view.bridge ? view.bridge.tierLevel : 0))
                        position: 0.0
                    }
                    GradientStop {
                        color: "transparent"
                        position: 1.0
                    }
                }
            }
            Column {
                anchors.left: parent.left
                anchors.leftMargin: Theme.spacingXl
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spacingSm

                Row {
                    spacing: Theme.spacingSm

                    Badge {
                        filled: view.bridge ? view.bridge.tierIsPeak : false
                        text: view.bridge ? view.bridge.tierLabel : ""
                        tone: view.bridge ? view.bridge.tierTone : "neutral"
                    }
                    Badge {
                        text: view.bridge ? view.bridge.storefront : ""
                        tone: "info"
                    }
                }
                Text {
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontDisplay
                    font.weight: Font.Bold
                    text: view.bridge ? (view.bridge.nextSaleText || "No campaign scheduled") : ""
                }
                Text {
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontMd
                    text: "Scan cadence follows the calendar: 6 h when quiet, 5 min during a mega sale."
                }
            }

            // A slow pulse on the right edge — ambient motion that says "this is live"
            // without competing with the text.
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: Theme.spacingXl
                anchors.verticalCenter: parent.verticalCenter
                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                border.width: 2
                color: "transparent"
                height: 96
                radius: Theme.radiusPill
                width: 96

                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: Theme.effectiveMotion > 0

                    NumberAnimation {
                        duration: Theme.durAmbient / 4
                        easing.type: Theme.easeAmbient
                        to: 0.25
                    }
                    NumberAnimation {
                        duration: Theme.durAmbient / 4
                        easing.type: Theme.easeAmbient
                        to: 0.8
                    }
                }
                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    running: Theme.effectiveMotion > 0

                    NumberAnimation {
                        duration: Theme.durAmbient / 4
                        easing.type: Theme.easeAmbient
                        to: 1.14
                    }
                    NumberAnimation {
                        duration: Theme.durAmbient / 4
                        easing.type: Theme.easeAmbient
                        to: 1.0
                    }
                }

                Text {
                    anchors.centerIn: parent
                    color: Theme.accent
                    font.pixelSize: Theme.fontDisplay
                    text: "⏱"
                }
            }
        }

        // ---- the rhythm, explained ------------------------------------------
        Text {
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontXl
            font.weight: Font.DemiBold
            text: "Shopee's sale rhythm"
        }
        Grid {
            columnSpacing: Theme.spacingMd
            columns: 2
            rowSpacing: Theme.spacingMd
            width: parent.width

            RhythmCard {
                cadence: "every 5 min"
                detail: "9.9, 11.11 and 12.12 — the deepest cuts of the year, and the ones that sell out fastest."
                tint: Theme.auroraA
                title: "Mega sale"
            }
            RhythmCard {
                cadence: "every 15 min"
                detail: "Any day whose number matches its month: 1.1, 2.2, … 10.10. Vouchers stack here."
                tint: Theme.auroraD
                title: "Double date"
            }
            RhythmCard {
                cadence: "every 30 min"
                detail: "The 15th, the 25th and month-end, when salaries land in Vietnam."
                tint: Theme.auroraB
                title: "Payday"
            }
            RhythmCard {
                cadence: "every 10 min"
                detail: "00:00, 09:00, 12:00, 15:00, 18:00 and 21:00 daily — short windows, real prices."
                tint: Theme.auroraC
                title: "Flash slots"
            }
        }
    }

    component RhythmCard: GlassPanel {
        id: rhythm

        property string cadence: ""
        property string detail: ""
        property color tint: Theme.accent
        property string title: ""

        height: 96
        radius: Theme.radiusMd
        width: (view.width - Theme.spacingMd) / 2

        Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.margins: 1
            anchors.top: parent.top
            color: rhythm.tint
            radius: Theme.radiusPill
            width: 3
        }
        Column {
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingMd + 4
            anchors.margins: Theme.spacingMd
            spacing: 4

            Row {
                spacing: Theme.spacingSm

                Text {
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontLg
                    font.weight: Font.DemiBold
                    text: rhythm.title
                }
                Badge {
                    anchors.verticalCenter: parent.verticalCenter
                    text: rhythm.cadence
                    tone: "neutral"
                }
            }
            Text {
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSm
                text: rhythm.detail
                width: rhythm.width - Theme.spacingXl
                wrapMode: Text.WordWrap
            }
        }
    }
}
