import QtQuick
import QtQuick.Controls.Basic
import Theme
import components

/*!
    The watchlist: what the app should keep an eye on between sale days.

    Note the wording on `minDiscount`: "min real discount". It is measured against observed
    history, not Shopee's claim (ADR-005), and the form says so — otherwise a user sets 50%
    and wonders why the "-50%" listings never appear.
*/
Item {
    id: view

    property var bridge: null

    // Both hooks: onCompleted covers the normal case, onBridgeChanged covers a bridge that
    // is assigned after this view was constructed (a lazily-loaded view, or a preview).
    Component.onCompleted: if (bridge)
        bridge.refreshWatches()
    onBridgeChanged: if (bridge)
        bridge.refreshWatches()

    Row {
        anchors.fill: parent
        spacing: Theme.spacingLg

        // ---- add form --------------------------------------------------------
        GlassPanel {
            height: parent.height
            width: 320

            Column {
                anchors.fill: parent
                anchors.margins: Theme.spacingLg
                spacing: Theme.spacingMd

                Text {
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontXl
                    font.weight: Font.DemiBold
                    text: "New watch"
                }
                Text {
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: "A watch is scanned automatically on the cadence the sale calendar sets."
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                FormLabel {
                    text: "Keyword"
                }
                SearchField {
                    id: keyword

                    glyph: ""
                    placeholder: "tai nghe bluetooth"
                    width: parent.width
                }
                FormLabel {
                    text: "Max price (₫)"
                }
                SearchField {
                    id: maxPrice

                    glyph: "≤"
                    numeric: true
                    placeholder: "500000 — blank for any"
                    width: parent.width
                }
                FormLabel {
                    text: "Min real discount (%)"
                }
                SearchField {
                    id: minDiscount

                    glyph: "%"
                    numeric: true
                    placeholder: "20"
                    width: parent.width
                }
                FormLabel {
                    text: "Min rating"
                }
                SearchField {
                    id: minRating

                    glyph: "★"
                    placeholder: "4.0 — blank for any"
                    width: parent.width
                }
                FormLabel {
                    text: "Exclude words"
                }
                SearchField {
                    id: exclude

                    glyph: "⊘"
                    placeholder: "op lung, cuong luc"
                    width: parent.width
                }
                Row {
                    spacing: Theme.spacingSm

                    Rectangle {
                        id: officialToggle

                        property bool checked: false

                        border.color: checked ? Theme.accent : Theme.glassBorder
                        border.width: Theme.borderThin
                        color: checked ? Theme.accent : Theme.glassFill
                        height: 22
                        radius: Theme.radiusPill
                        width: 38

                        Behavior on color {
                            ColorAnimation {
                                duration: Theme.durFast
                            }
                        }

                        Rectangle {
                            color: Theme.textPrimary
                            height: 16
                            radius: Theme.radiusPill
                            width: 16
                            x: officialToggle.checked ? officialToggle.width - width - 3 : 3
                            y: 3

                            Behavior on x {
                                NumberAnimation {
                                    duration: Theme.durFast
                                    easing.type: Theme.easeStandard
                                }
                            }
                        }
                        TapHandler {
                            onTapped: officialToggle.checked = !officialToggle.checked
                        }
                        HoverHandler {
                            cursorShape: Qt.PointingHandCursor
                        }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontMd
                        text: "Official shops only"
                    }
                }
                GradientButton {
                    iconText: "+"
                    text: "Add watch"
                    width: parent.width

                    onClicked: {
                        if (!view.bridge)
                            return;
                        view.bridge.addWatch(keyword.text, parseInt(maxPrice.text) || 0, parseFloat(minDiscount.text) || 20, parseFloat(minRating.text) || 0, exclude.text, officialToggle.checked);
                        keyword.text = "";
                        maxPrice.text = "";
                        exclude.text = "";
                    }
                }
            }
        }

        // ---- list ------------------------------------------------------------
        Item {
            height: parent.height
            width: parent.width - 320 - Theme.spacingLg

            ListView {
                id: watchList

                anchors.fill: parent
                clip: true
                model: view.bridge ? view.bridge.watches : null
                spacing: Theme.spacingSm
                visible: count > 0

                delegate: GlassPanel {
                    height: 76
                    hovered: rowHover.hovered
                    interactive: true
                    opacity: model.enabled ? 1.0 : 0.5
                    width: watchList.width

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Theme.durFast
                        }
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.spacingLg
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3

                        Text {
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontLg
                            font.weight: Font.DemiBold
                            text: model.keyword
                        }
                        Row {
                            spacing: Theme.spacingSm

                            Badge {
                                text: "≤ " + model.maxPriceText
                            }
                            Badge {
                                text: "−" + model.minDiscount.toFixed(0) + "% real"
                                tone: "accent"
                            }
                            Badge {
                                text: "★ " + model.minRating.toFixed(1)
                                visible: model.minRating > 0
                            }
                            Badge {
                                text: "official"
                                tone: "info"
                                visible: model.officialOnly
                            }
                            Badge {
                                text: "⊘ " + model.excludeText
                                tone: "caution"
                                visible: model.excludeText.length > 0
                            }
                        }
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.spacingLg
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.spacingSm

                        GradientButton {
                            flat: true
                            horizontalPadding: Theme.spacingMd
                            text: model.enabled ? "Pause" : "Resume"

                            onClicked: if (view.bridge)
                                view.bridge.setWatchEnabled(model.watchId, !model.enabled)
                        }
                        GradientButton {
                            flat: true
                            horizontalPadding: Theme.spacingMd
                            text: "Remove"

                            onClicked: if (view.bridge)
                                view.bridge.removeWatch(model.watchId)
                        }
                    }
                    HoverHandler {
                        id: rowHover

                    }
                }
            }
            EmptyState {
                anchors.centerIn: parent
                body: "Add one on the left. Watches are what make this a hunter rather than a " + "search box — they get scanned on their own, harder as a sale day approaches."
                glyph: "☰"
                title: "No watches yet"
                visible: watchList.count === 0
            }
        }
    }

    component FormLabel: Text {
        color: Theme.textSecondary
        font.capitalization: Font.AllUppercase
        font.family: Theme.fontFamily
        font.letterSpacing: 0.6
        font.pixelSize: Theme.fontXs
    }
}
