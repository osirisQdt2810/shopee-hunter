import QtQuick
import QtQuick.Controls.Basic
import Theme
import components

/*!
    The main view: a search bar and the ranked deal list.

    Ordering is the model's (score descending, set by `core.deals.rank_deals`) — this view
    never re-sorts, because "which deal is best" is a judgement and judgements live in core.
*/
Item {
    id: view

    property var bridge: null

    function runSearch() {
        if (!view.bridge)
            return;
        const maxPrice = parseInt(priceField.text) || 0;
        const minDiscount = parseFloat(discountField.text) || 0;
        view.bridge.searchKeyword(keywordField.text, maxPrice, minDiscount);
    }

    Column {
        anchors.fill: parent
        spacing: Theme.spacingMd

        // ---- search row ------------------------------------------------------
        Row {
            spacing: Theme.spacingSm
            width: parent.width

            SearchField {
                id: keywordField

                placeholder: "Search Shopee — e.g. tai nghe bluetooth"
                width: parent.width - priceField.width - discountField.width - searchButton.width - scanButton.width - Theme.spacingSm * 4

                onAccepted: view.runSearch()
            }
            SearchField {
                id: priceField

                glyph: "≤"
                numeric: true
                placeholder: "Max price"
                width: 148

                onAccepted: view.runSearch()
            }
            SearchField {
                id: discountField

                glyph: "%"
                numeric: true
                placeholder: "Min off"
                width: 122

                onAccepted: view.runSearch()
            }
            GradientButton {
                id: searchButton

                busy: view.bridge ? view.bridge.busy : false
                enabled: !(view.bridge && view.bridge.busy)
                iconText: "⌕"
                text: "Search"

                onClicked: view.runSearch()
            }
            GradientButton {
                id: scanButton

                enabled: !(view.bridge && view.bridge.busy)
                flat: true
                text: "Scan watches"

                onClicked: if (view.bridge)
                    view.bridge.scanNow()
            }
        }

        // ---- progress --------------------------------------------------------
        GlassPanel {
            elevated: false
            height: visible ? 34 : 0
            radius: Theme.radiusMd
            visible: view.bridge ? view.bridge.busy : false
            width: parent.width

            Row {
                anchors.left: parent.left
                anchors.leftMargin: Theme.spacingMd
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spacingSm

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: progressTracker.label
                }
            }

            // Indeterminate shimmer rather than a fake percentage: a scan's total request
            // count is not known until the source answers.
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.margins: 1
                anchors.right: parent.right
                clip: true
                color: "transparent"
                height: 2

                Rectangle {
                    id: shimmer

                    height: parent.height
                    radius: 1
                    width: parent.width * 0.28

                    gradient: Gradient {
                        orientation: Gradient.Horizontal

                        GradientStop {
                            color: "transparent"
                            position: 0.0
                        }
                        GradientStop {
                            color: Theme.accent
                            position: 0.5
                        }
                        GradientStop {
                            color: "transparent"
                            position: 1.0
                        }
                    }
                    SequentialAnimation on x {
                        loops: Animation.Infinite
                        running: view.bridge ? view.bridge.busy && Theme.effectiveMotion > 0 : false

                        NumberAnimation {
                            duration: 1200
                            from: -shimmer.width
                            to: shimmer.parent.width
                        }
                    }
                }
            }
            QtObject {
                id: progressTracker

                property string label: "Scanning…"
            }
            Connections {
                function onScanProgress(done, total, label) {
                    progressTracker.label = total > 0 ? "Scanning " + (done + 1) + "/" + total + " — " + label : "Scanning — " + label;
                }

                target: view.bridge
            }
        }

        // ---- results ---------------------------------------------------------
        Item {
            height: parent.height - y
            width: parent.width

            ListView {
                id: list

                anchors.fill: parent
                boundsBehavior: Flickable.StopAtBounds
                cacheBuffer: 400
                clip: true
                model: view.bridge ? view.bridge.deals : null
                spacing: Theme.spacingSm
                visible: count > 0

                ScrollBar.vertical: ScrollBar {
                    id: scroller

                    policy: list.contentHeight > list.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

                    // `implicitHeight` matters: without it the handle Rectangle fills the
                    // whole track and reads as a stray vertical rule down the window.
                    contentItem: Rectangle {
                        color: scroller.pressed ? Theme.accent : Theme.glassBorderStrong
                        implicitHeight: 40
                        implicitWidth: 4
                        opacity: scroller.active ? 1.0 : 0.35
                        radius: 2

                        Behavior on opacity {
                            NumberAnimation {
                                duration: Theme.durBase
                            }
                        }
                    }
                }
                delegate: DealCard {
                    claimedDiscount: model.claimedDiscount
                    confidence: model.confidence
                    confidenceLabel: model.confidenceLabel
                    discount: model.discount
                    flags: model.flags
                    flash: model.flash
                    genuine: model.genuine
                    history: model.history
                    imageUrl: model.imageUrl
                    index: model.index
                    name: model.name
                    official: model.official
                    priceText: model.priceText
                    ratingText: model.ratingText
                    referenceText: model.referenceText
                    savingsText: model.savingsText
                    score: model.score
                    shopName: model.shopName
                    soldText: model.soldText
                    warnings: model.warnings
                    width: list.width - Theme.spacingSm

                    onOpened: if (view.bridge)
                        view.bridge.openUrl(model.url)
                }
            }
            EmptyState {
                actionText: "Scan my watches"
                anchors.centerIn: parent
                body: "Search for something, or run a scan of your watches. Sale Hunter compares " + "today's price against what this listing has actually sold for — so the " + "first scan builds history and later scans get sharper."
                glyph: "◎"
                title: "No verified deals yet"
                visible: list.count === 0 && !(view.bridge && view.bridge.busy)

                onActionTriggered: if (view.bridge)
                    view.bridge.scanNow()
            }
        }
    }
}
