import QtQuick
import QtQuick.Effects
import Theme

/*!
    One deal. The card's job is to make a single judgement readable at a glance: how big the
    drop is, and how much we trust it.

    Layout intent, because it is a deliberate hierarchy rather than a pile of fields:
      * the discount and the price are the largest things on the card — the answer;
      * the reference price sits struck-through beside it — what the drop is measured against;
      * the score ring and sparkline are the *evidence*, on the right;
      * warnings ("inflated claim", "unrated seller") are never mixed in with the positive
        badges — a fake discount must not be able to look like a feature.

    Every value arrives pre-formatted from `gui/models.py`; this file computes nothing.
*/
Item {
    id: card

    property bool claimInflated: false
    property real claimedDiscount: 0
    property string confidence: "none"
    property string confidenceLabel: ""
    property real discount: 0
    property var flags: []
    property bool flash: false
    property bool genuine: true
    property var history: []
    property string imageUrl: ""
    property int index: 0
    property string name: ""
    property bool official: false
    property string priceText: ""
    property string ratingText: ""
    property string referenceText: ""
    property string savingsText: ""
    property real score: 0
    property string shopName: ""
    property string soldText: ""
    property var warnings: []

    signal opened

    implicitHeight: 128

    // Staggered entrance: each card starts slightly lower and transparent, delayed by its
    // row. It is the difference between a list that appears and a list that arrives.
    opacity: 0

    transform: Translate {
        id: lift

        y: 14
    }

    Component.onCompleted: {
        if (Theme.effectiveMotion <= 0) {
            card.opacity = 1;
            lift.y = 0;
        } else {
            entrance.start();
        }
    }

    SequentialAnimation {
        id: entrance

        PauseAnimation {
            duration: Math.min(card.index, 12) * Math.round(35 * Theme.effectiveMotion)
        }
        ParallelAnimation {
            NumberAnimation {
                duration: Theme.durBase
                property: "opacity"
                target: card
                to: 1
            }
            NumberAnimation {
                duration: Theme.durSlow
                easing.type: Theme.easeStandard
                property: "y"
                target: lift
                to: 0
            }
        }
    }
    GlassPanel {
        id: surface

        anchors.fill: parent
        hovered: hover.hovered
        interactive: true
        scale: hover.hovered ? 1.006 : 1.0

        Behavior on scale {
            NumberAnimation {
                duration: Theme.durFast
                easing.type: Theme.easeStandard
            }
        }

        // Thumbnail. A remote image may never load (Shopee's CDN blocks hotlinks from some
        // regions), so the gradient placeholder is the default and the image sits on top of
        // it — the card must never show a grey hole.
        Rectangle {
            id: thumb

            anchors.left: parent.left
            anchors.leftMargin: Theme.spacingMd
            anchors.verticalCenter: parent.verticalCenter
            antialiasing: true
            height: 88
            radius: Theme.radiusMd
            width: 88

            gradient: Gradient {
                GradientStop {
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)
                    position: 0.0
                }
                GradientStop {
                    color: Qt.rgba(Theme.auroraB.r, Theme.auroraB.g, Theme.auroraB.b, 0.24)
                    position: 1.0
                }
            }

            Text {
                anchors.centerIn: parent
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontDisplay
                font.weight: Font.Bold
                opacity: 0.7
                text: card.name.length > 0 ? card.name.charAt(0).toUpperCase() : "?"
                visible: thumbImage.status !== Image.Ready
            }

            // Rounded thumbnail without shipping a mask asset: the rounded shape is
            // rendered offscreen and used as an alpha mask. Qt Quick's `clip` only clips to
            // the bounding RECT, so a radius alone would leave square photo corners poking
            // out of the card.
            Item {
                id: maskShape

                height: thumb.height
                layer.enabled: true
                visible: false
                width: thumb.width

                Rectangle {
                    anchors.fill: parent
                    color: "white"
                    radius: Theme.radiusMd
                }
            }
            Image {
                id: thumbImage

                anchors.fill: parent
                asynchronous: true
                cache: true
                fillMode: Image.PreserveAspectCrop
                source: card.imageUrl
                visible: false
            }
            MultiEffect {
                anchors.fill: parent
                maskEnabled: true
                maskSource: maskShape
                opacity: thumbImage.status === Image.Ready ? 1 : 0
                source: thumbImage
                visible: thumbImage.status === Image.Ready

                Behavior on opacity {
                    NumberAnimation {
                        duration: Theme.durBase
                    }
                }
            }
            Badge {
                anchors.left: parent.left
                anchors.margins: 4
                anchors.top: parent.top
                filled: true
                text: "⚡ flash"
                tone: "caution"
                visible: card.flash
            }
        }

        // ---- left column: the answer -----------------------------------------
        Column {
            anchors.left: thumb.right
            anchors.leftMargin: Theme.spacingMd
            anchors.right: evidence.left
            anchors.rightMargin: Theme.spacingMd
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5

            Text {
                color: Theme.textPrimary
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontLg
                font.weight: Font.DemiBold
                maximumLineCount: 1
                text: card.name
                width: parent.width
            }
            Row {
                spacing: Theme.spacingSm

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.scoreColor(card.score)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontXl
                    font.weight: Font.Bold
                    text: "−" + card.discount.toFixed(0) + "%"
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontLg
                    font.weight: Font.DemiBold
                    text: card.priceText
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    font.strikeout: true
                    text: card.referenceText
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.positive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: "save " + card.savingsText
                    visible: card.savingsText.length > 0
                }
            }
            Row {
                spacing: Theme.spacingSm

                Badge {
                    text: card.confidenceLabel
                    tone: card.confidence === "high" ? "positive" : card.confidence === "medium" ? "info" : card.confidence === "low" ? "caution" : "negative"
                }
                Repeater {
                    model: card.flags

                    Badge {
                        text: modelData
                        tone: "neutral"
                    }
                }

                // Warnings are visually separated, and always amber/red — the whole point of
                // the app is that a big claimed discount can be the *bad* signal.
                Repeater {
                    model: card.warnings

                    Badge {
                        text: "⚠ " + modelData
                        tone: "caution"
                    }
                }
            }
            Row {
                spacing: Theme.spacingMd

                Text {
                    color: card.official ? Theme.info : Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: (card.official ? "✓ " : "") + card.shopName
                    visible: card.shopName.length > 0
                }
                Text {
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: "★ " + card.ratingText
                    visible: card.ratingText.length > 0
                }
                Text {
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: card.soldText
                    visible: card.soldText.length > 0
                }
                Text {
                    color: card.claimInflated ? Theme.caution : Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSm
                    text: "Shopee claims −" + card.claimedDiscount + "%"
                    visible: card.claimedDiscount > 0
                }
            }
        }

        // ---- right column: the evidence --------------------------------------
        Column {
            id: evidence

            anchors.right: parent.right
            anchors.rightMargin: Theme.spacingMd
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spacingSm
            width: 118

            ScoreRing {
                anchors.horizontalCenter: parent.horizontalCenter
                score: card.score
            }
            Sparkline {
                lineColor: Theme.scoreColor(card.score)
                points: card.history
                width: parent.width
            }
        }

        // A hover-revealed "open" affordance rather than a permanent button: the card is
        // already dense, and the whole surface is clickable anyway.
        Rectangle {
            anchors.margins: Theme.spacingSm
            anchors.right: parent.right
            anchors.top: parent.top
            border.color: Theme.glassBorderStrong
            border.width: Theme.borderThin
            color: Theme.glassFillStrong
            height: 26
            opacity: hover.hovered ? 1 : 0
            radius: Theme.radiusPill
            width: 26

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.durFast
                }
            }

            Text {
                anchors.centerIn: parent
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontMd
                text: "↗"
            }
        }
    }
    HoverHandler {
        id: hover

        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        onTapped: card.opened()
    }
}
