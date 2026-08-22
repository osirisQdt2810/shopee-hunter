import QtQuick
import QtQuick.Effects
import Theme

/*!
    The animated gradient behind everything: a dark base wash plus four slowly drifting
    coloured blobs, blurred into one another.

    Why blobs-and-blur rather than a single animated LinearGradient: a moving linear gradient
    reads as a screen wipe, while overlapping radials that breathe at different periods never
    visibly repeat. The periods below are intentionally coprime-ish for that reason.

    Cost control: the blobs live in ONE layered item, so the whole thing is a single blur pass
    per frame regardless of blob count, and the animations pause when the window is hidden.
*/
Item {
    id: root

    property bool active: true
    property real intensity: 1.0

    // Base wash. Painted, not native — the app must look like this with the OS blur absent.
    Rectangle {
        anchors.fill: parent

        gradient: Gradient {
            GradientStop {
                color: Theme.bgDeep
                position: 0.0
            }
            GradientStop {
                color: Theme.bgBase
                position: 0.55
            }
            GradientStop {
                color: Theme.bgDeep
                position: 1.0
            }
        }
    }
    Item {
        id: blobs

        anchors.fill: parent
        layer.enabled: true
        opacity: 0.85 * root.intensity

        layer.effect: MultiEffect {
            blur: 1.0
            blurEnabled: true
            blurMax: 64
            blurMultiplier: 1.4
            saturation: 0.15
        }

        Blob {
            height: width
            period: Theme.durAmbient
            tint: Theme.auroraA
            width: parent.width * 0.85
            x: -parent.width * 0.18
            y: -parent.height * 0.35
        }
        Blob {
            driftX: 0.09
            height: width
            period: Theme.durAmbient * 1.4
            tint: Theme.auroraB
            width: parent.width * 0.7
            x: parent.width * 0.55
            y: -parent.height * 0.2
        }
        Blob {
            driftY: 0.05
            height: width
            period: Theme.durAmbient * 1.9
            tint: Theme.auroraC
            width: parent.width * 0.6
            x: parent.width * 0.1
            y: parent.height * 0.6
        }
        Blob {
            driftX: 0.07
            height: width
            period: Theme.durAmbient * 1.15
            tint: Theme.auroraD
            width: parent.width * 0.5
            x: parent.width * 0.7
            y: parent.height * 0.55
        }
    }

    // A dark scrim over the blobs. Without it the aurora fights every piece of text on top of
    // it; with it, the colour reads as light *behind* the glass. Tuned against the deal list,
    // which is the densest text in the app — at 0.55 the teal blob was winning against a
    // card's secondary text.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.02, 0.03, 0.06, 0.68)
    }

    // Fine noise breaks up the banding a large smooth gradient shows on 8-bit panels.
    Canvas {
        anchors.fill: parent
        opacity: 0.022

        onPaint: {
            const ctx = getContext("2d");
            const cell = 3;
            for (let y = 0; y < height; y += cell) {
                for (let x = 0; x < width; x += cell) {
                    const v = Math.random() * 255;
                    ctx.fillStyle = Qt.rgba(v / 255, v / 255, v / 255, 1);
                    ctx.fillRect(x, y, cell, cell);
                }
            }
        }
    }

    component Blob: Rectangle {
        property real driftX: 0.12
        property real driftY: 0.08
        property int period: Theme.durAmbient
        property color tint: Theme.auroraA

        radius: width / 2

        gradient: Gradient {
            GradientStop {
                color: Qt.rgba(tint.r, tint.g, tint.b, 0.42)
                position: 0.0
            }
            GradientStop {
                color: Qt.rgba(tint.r, tint.g, tint.b, 0.12)
                position: 0.6
            }
            GradientStop {
                color: "transparent"
                position: 1.0
            }
        }

        // Two independent animations per blob (x and y at different periods) trace a
        // Lissajous path, so the motion never loops visibly.
        SequentialAnimation on x {
            loops: Animation.Infinite
            running: root.active && Theme.effectiveMotion > 0

            NumberAnimation {
                duration: period
                easing.type: Theme.easeAmbient
                to: parent ? parent.width * driftX : 0
            }
            NumberAnimation {
                duration: period * 1.3
                easing.type: Theme.easeAmbient
                to: parent ? -parent.width * driftX * 0.6 : 0
            }
        }
        SequentialAnimation on y {
            loops: Animation.Infinite
            running: root.active && Theme.effectiveMotion > 0

            NumberAnimation {
                duration: period * 1.7
                easing.type: Theme.easeAmbient
                to: parent ? parent.height * driftY : 0
            }
            NumberAnimation {
                duration: period * 1.1
                easing.type: Theme.easeAmbient
                to: parent ? -parent.height * driftY : 0
            }
        }
    }
}
