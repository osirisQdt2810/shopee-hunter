import QtQuick
import Theme
import components

/*!
    Settings, and — just as importantly — the app's own disclosure about how it behaves.

    The rate-limit section is not a tuning panel. It explains why the limits exist (ADR-007)
    and shows the values as read-only facts: the realistic worst outcome of this app is a
    flagged account, and a "turbo" slider would be the feature that causes it.
*/
Item {
    id: view

    property var bridge: null

    Column {
        anchors.fill: parent
        spacing: Theme.spacingLg

        Row {
            spacing: Theme.spacingMd
            width: parent.width

            GlassPanel {
                height: 210
                width: (parent.width - Theme.spacingMd) / 2

                Column {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingLg
                    spacing: Theme.spacingSm

                    Text {
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontXl
                        font.weight: Font.DemiBold
                        text: "Data source"
                    }
                    Text {
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSm
                        text: "Sources are tried in order until one answers. Being refused is normal — " + "the app falls through rather than reporting “no deals”."
                        width: parent.width
                        wrapMode: Text.WordWrap
                    }
                    Row {
                        spacing: Theme.spacingSm

                        Badge {
                            text: view.bridge && view.bridge.sourceUsed.length > 0 ? "answered by " + view.bridge.sourceUsed : "no scan yet"
                            tone: "info"
                        }
                        Badge {
                            filled: true
                            text: "demo mode"
                            tone: "caution"
                            visible: view.bridge ? view.bridge.demoMode : false
                        }
                    }
                    Text {
                        color: Theme.textMuted
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSm
                        lineHeight: 1.4
                        text: "1. Affiliate API — official and stable, needs your own keys.\n" + "2. Browser — your logged-in session; the most reliable.\n" + "3. Web API — needs cookies pasted from a browser."
                        width: parent.width
                        wrapMode: Text.WordWrap
                    }
                }
            }
            GlassPanel {
                height: 210
                width: (parent.width - Theme.spacingMd) / 2

                Column {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingLg
                    spacing: Theme.spacingSm

                    Text {
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontXl
                        font.weight: Font.DemiBold
                        text: "Why it scans slowly"
                    }
                    Text {
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSm
                        lineHeight: 1.35
                        text: "Every request passes a token bucket at roughly one every two seconds, " + "with at most two in flight. This is a personal watcher, not a crawler: " + "the worst outcome here is not a missed discount, it is your account " + "getting flagged."
                        width: parent.width
                        wrapMode: Text.WordWrap
                    }
                    Row {
                        spacing: Theme.spacingSm

                        Badge {
                            text: "0.5 req/s"
                            tone: "positive"
                        }
                        Badge {
                            text: "burst 4"
                            tone: "positive"
                        }
                        Badge {
                            text: "2 concurrent"
                            tone: "positive"
                        }
                        Badge {
                            text: "block → 120 s cooldown"
                            tone: "caution"
                        }
                    }
                }
            }
        }
        GlassPanel {
            height: 150
            width: parent.width

            Column {
                anchors.fill: parent
                anchors.margins: Theme.spacingLg
                spacing: Theme.spacingSm

                Text {
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontXl
                    font.weight: Font.DemiBold
                    text: "How a discount is judged"
                }
                Text {
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontMd
                    lineHeight: 1.35
                    text: "Shopee's “-50%” is a seller-controlled claim. Sale Hunter compares today's " + "price against the median of what this listing has actually sold for over " + "the last 90 days, excluding flash prices. When the claim is much larger " + "than the observed drop, the deal is flagged “inflated claim” — and it is " + "not counted as genuine."
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Row {
                    spacing: Theme.spacingSm

                    Badge {
                        text: "well verified"
                        tone: "positive"
                    }
                    Badge {
                        text: "verified"
                        tone: "info"
                    }
                    Badge {
                        text: "thin history"
                        tone: "caution"
                    }
                    Badge {
                        text: "unverified"
                        tone: "negative"
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.textMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSm
                        text: "— shown on every card, so you always know how much evidence there is."
                    }
                }
            }
        }
    }
}
