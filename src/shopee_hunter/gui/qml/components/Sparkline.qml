import QtQuick
import Theme

/*!
    Price history as a filled line. Receives points already normalised to 0..1 by
    `gui/models.py` — the delegate draws, it does not scale, so it cannot invent an axis of
    its own (and a chart that lies about its own scale is worse than no chart).

    The last point is the current price and gets a dot, because "where are we now relative to
    the past 90 days" is the only question this widget answers.
*/
Item {
    id: spark

    property color lineColor: Theme.positive
    property var points: []
    property real revealed: 0

    implicitHeight: 34
    visible: points && points.length > 1

    onPointsChanged: {
        revealed = 0;
        if (Theme.effectiveMotion > 0)
            reveal.restart();
        else
            revealed = 1;
        canvas.requestPaint();
    }
    onRevealedChanged: canvas.requestPaint()

    NumberAnimation {
        id: reveal

        duration: Math.max(1, Theme.durSlow)
        easing.type: Theme.easeStandard
        from: 0
        property: "revealed"
        target: spark
        to: 1
    }
    Canvas {
        id: canvas

        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const pts = spark.points;
            if (!pts || pts.length < 2)
                return;

            const pad = 3;
            const w = width - pad * 2;
            const h = height - pad * 2;
            const shown = Math.max(2, Math.ceil(pts.length * spark.revealed));

            // Values are 0 = cheapest, 1 = dearest, so y is inverted: cheap sits low on the
            // chart, which is where a shopper expects "good" to be.
            function px(i) {
                return pad + (w * i / (pts.length - 1));
            }
            function py(i) {
                return pad + h - (pts[i] * h);
            }

            ctx.beginPath();
            ctx.moveTo(px(0), py(0));
            for (let i = 1; i < shown; ++i)
                ctx.lineTo(px(i), py(i));

            const fill = ctx.createLinearGradient(0, 0, 0, height);
            fill.addColorStop(0, Qt.rgba(spark.lineColor.r, spark.lineColor.g, spark.lineColor.b, 0.28));
            fill.addColorStop(1, Qt.rgba(spark.lineColor.r, spark.lineColor.g, spark.lineColor.b, 0.0));

            ctx.lineTo(px(shown - 1), pad + h);
            ctx.lineTo(px(0), pad + h);
            ctx.closePath();
            ctx.fillStyle = fill;
            ctx.fill();

            ctx.beginPath();
            ctx.moveTo(px(0), py(0));
            for (let i = 1; i < shown; ++i)
                ctx.lineTo(px(i), py(i));
            ctx.strokeStyle = spark.lineColor;
            ctx.lineWidth = 1.6;
            ctx.lineJoin = "round";
            ctx.stroke();

            if (shown === pts.length) {
                ctx.beginPath();
                ctx.arc(px(pts.length - 1), py(pts.length - 1), 2.6, 0, Math.PI * 2);
                ctx.fillStyle = spark.lineColor;
                ctx.fill();
            }
        }
    }
}
