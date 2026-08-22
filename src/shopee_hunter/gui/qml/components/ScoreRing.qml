import QtQuick
import Theme

/*!
    The 0–100 deal score as an arc that animates from empty on first paint.

    Drawn on a Canvas rather than composed from Rectangles because an arc with a rounded cap
    and a gradient stroke is exactly what Canvas is for; the alternative is a ShaderEffect,
    which would be faster and far harder to read for one small widget per card.
*/
Item {
    id: ring

    property real animatedScore: 0
    property real score: 0
    property int thickness: 4

    implicitHeight: 52
    implicitWidth: 52

    Component.onCompleted: {
        if (Theme.effectiveMotion > 0)
            scoreAnimation.restart();
        else
            ring.animatedScore = ring.score;
    }
    onAnimatedScoreChanged: canvas.requestPaint()
    onScoreChanged: scoreAnimation.restart()

    NumberAnimation {
        id: scoreAnimation

        duration: Math.max(1, Theme.durSlow)
        easing.type: Theme.easeStandard
        from: 0
        property: "animatedScore"
        target: ring
        to: ring.score
    }
    Canvas {
        id: canvas

        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const cx = width / 2;
            const cy = height / 2;
            const r = Math.min(width, height) / 2 - ring.thickness;
            const start = -Math.PI / 2;
            const sweep = Math.PI * 2 * Math.max(0, Math.min(ring.animatedScore, 100)) / 100;

            ctx.lineWidth = ring.thickness;
            ctx.lineCap = "round";

            ctx.strokeStyle = Qt.rgba(1, 1, 1, 0.10);
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.stroke();

            if (sweep > 0.01) {
                ctx.strokeStyle = Theme.scoreColor(ring.score);
                ctx.beginPath();
                ctx.arc(cx, cy, r, start, start + sweep);
                ctx.stroke();
            }
        }
    }
    Column {
        anchors.centerIn: parent
        spacing: -2

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontLg
            font.weight: Font.Bold
            text: Math.round(ring.animatedScore)
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontXs - 1
            text: "score"
        }
    }
}
