pragma Singleton
import QtQuick

/*!
    Every visual token in the app. A literal colour, radius, duration or font size anywhere
    else is a review defect (ADR-002) — this file is what makes the two platforms look
    identical and a restyle a one-file change.

    Structure:
      * palette       — surfaces, text, accents, semantic colours
      * geometry      — radii, spacing, border widths, elevation
      * type          — font family and the size ramp
      * motion        — durations and easings, all scaled by `motionScale`
      * gradients     — the reusable gradient stops (declared as functions)
*/
QtObject {
    id: theme

    // ---------------------------------------------------------------- runtime
    // Bound once from settings by AppWindow. Kept as plain properties rather than read
    // straight from the bridge so a QML-only preview (qmlscene, a unit test) still renders.
    property color accent: "#FF5722"
    readonly property color accentGlow: Qt.rgba(accent.r, accent.g, accent.b, 0.42)
    readonly property color accentSoft: Qt.rgba(accent.r, accent.g, accent.b, 0.16)

    // The aurora blobs behind everything. Shopee orange leads; violet and cyan keep it from
    // looking like a single flat wash.
    readonly property color auroraA: "#FF5722"
    readonly property color auroraB: "#7C4DFF"
    readonly property color auroraC: "#00BCD4"
    readonly property color auroraD: "#FF2E93"

    // The scrim that sits between the aurora blobs and the content. Deliberately not bgDeep:
    // it is a translucent wash, and reading it as "the deep background colour" would make a
    // restyle of bgDeep silently change how much of the aurora shows through.
    readonly property color auroraScrim: Qt.rgba(0.02, 0.03, 0.06, 0.68)
    readonly property color bgBase: "#0B0E17"

    // ---------------------------------------------------------------- palette
    // Deep, slightly blue-black. Pure #000 makes translucency look like a hole rather than
    // like glass, and crushes the shadows the depth cues rely on.
    readonly property color bgDeep: "#07090F"
    readonly property color bgRaised: "#121727"
    readonly property int borderThin: 1
    readonly property color caution: "#FFB020"
    readonly property int durAmbient: Math.round(9000 * Math.max(effectiveMotion, 0.001))
    readonly property int durBase: Math.round(240 * effectiveMotion)

    // ----------------------------------------------------------------- motion
    readonly property int durFast: Math.round(140 * effectiveMotion)
    readonly property int durSlow: Math.round(420 * effectiveMotion)

    // One sweep of a looping progress shimmer. Clamped like durAmbient rather than scaled to
    // zero: this drives an infinite loop, and a zero-duration NumberAnimation on a loop spins
    // the frame timer instead of stopping. Call sites gate on effectiveMotion to stop it.
    readonly property int durSweep: Math.round(1200 * Math.max(effectiveMotion, 0.001))
    readonly property int easeAmbient: Easing.InOutSine
    readonly property int easeEnter: Easing.OutBack
    readonly property int easeExit: Easing.InCubic
    readonly property int easeStandard: Easing.OutCubic

    // Accessibility: motion collapses to zero in ONE place rather than being conditionally
    // skipped at every call site, so a component cannot forget to honour it.
    readonly property real effectiveMotion: reducedMotion ? 0.0 : Math.max(0.0, motionScale)
    readonly property int fontDisplay: 27

    // ------------------------------------------------------------------- type
    // A stack, not one family: the same declaration has to resolve on macOS and Windows, and
    // a missing family silently falls back to something with different metrics.
    readonly property string fontFamily: Qt.platform.os === "windows" ? "Segoe UI, Inter, Helvetica Neue, Arial" : "SF Pro Text, Inter, Helvetica Neue, Arial"

    // The oversized glyph an empty state leads with. Larger than fontHero because it is an
    // illustration rather than text, and it must not track a heading size that gets retuned.
    readonly property int fontGlyph: 52
    readonly property int fontHero: 38
    readonly property int fontLg: 15
    readonly property int fontMd: 13
    readonly property string fontMono: Qt.platform.os === "windows" ? "Cascadia Mono, Consolas, Menlo, monospace" : "SF Mono, Menlo, Consolas, monospace"
    readonly property int fontSm: 12
    readonly property int fontXl: 19
    readonly property int fontXs: 10

    // Smaller than fontXs and used for exactly one thing: the glyph inside a traffic-light
    // dot, which is 12px across. It is a token so the type ramp can be retuned as a ramp.
    readonly property int fontXxs: 8
    readonly property color glassBorder: Qt.rgba(1, 1, 1, 0.13)
    readonly property color glassBorderStrong: Qt.rgba(1, 1, 1, 0.18)

    // Glass surfaces are white at low alpha, NOT a lighter opaque grey: alpha is what lets
    // the animated background and the OS blur show through and read as one material.
    readonly property color glassFill: Qt.rgba(1, 1, 1, 0.075)
    readonly property color glassFillHover: Qt.rgba(1, 1, 1, 0.135)
    readonly property color glassFillStrong: Qt.rgba(1, 1, 1, 0.105)
    readonly property color glassHighlight: Qt.rgba(1, 1, 1, 0.30)
    readonly property int headerHeight: 68
    readonly property color info: "#5B9DFF"

    // Not a colour anyone sees: the fill of an invisible MultiEffect alpha mask, where the
    // channel value means "fully opaque" rather than "white". A token so the literal check
    // does not need a named-colour exemption it would then have to police.
    readonly property color maskOpaque: "#FFFFFF"
    property real motionScale: 1.0
    property bool nativeBlur: false
    readonly property color negative: "#FF5A6E"

    // The film grain over the aurora. Low enough to read as texture rather than dirt; a
    // token because it is a look, and the only other place it could live is a magic 0.022.
    readonly property real noiseOpacity: 0.022

    // Surfaces that were hand-mixing their own near-black / near-white and so opted out of a
    // restyle. Each one is the *only* definition of that surface, so changing the palette
    // here now actually moves them.
    readonly property color panelShadow: Qt.rgba(0, 0, 0, 0.45)

    // Semantic colours. "Good deal" is green, an inflated claim is amber, an error is red —
    // and score colouring uses the same three so a badge and a ring never disagree.
    readonly property color positive: "#2DD4A7"
    readonly property int radiusLg: 20
    readonly property int radiusMd: 14
    readonly property int radiusPill: 999

    // --------------------------------------------------------------- geometry
    readonly property int radiusSm: 8
    readonly property int radiusXl: 28
    property bool reducedMotion: false
    readonly property color ringTrack: Qt.rgba(1, 1, 1, 0.10)
    readonly property int sidebarWidth: 224
    readonly property int spacingLg: 22
    readonly property int spacingMd: 14
    readonly property int spacingSm: 8
    readonly property int spacingXl: 34
    readonly property int spacingXs: 4
    readonly property color textMuted: Qt.rgba(0.95, 0.96, 1.0, 0.40)
    readonly property color textOnAccent: "#FFFFFF"
    readonly property color textPrimary: "#F2F4FA"
    readonly property color textSecondary: Qt.rgba(0.95, 0.96, 1.0, 0.66)
    readonly property int titleBarHeight: 40

    // macOS traffic-light colours. These are the ONE place the app copies a platform
    // convention rather than defining its own: a close button that is not that red reads as
    // a fake window. Tokens rather than literals so TitleBar stays free of hex codes.
    readonly property color trafficClose: "#FF5F57"
    readonly property color trafficGlyph: Qt.rgba(0, 0, 0, 0.55)
    readonly property color trafficMaximise: "#28C840"
    readonly property color trafficMinimise: "#FEBC2E"
    readonly property int windowRadius: 18

    function confidenceColor(confidence) {
        switch (confidence) {
        case "high":
            return positive;
        case "medium":
            return info;
        case "low":
            return caution;
        default:
            return negative;
        }
    }

    // ------------------------------------------------------------------ misc
    // Score → colour, in one place, so the ring, the badge and the sparkline agree.
    // Grade -> colour. The BANDS live in core/deals.py (`score_grade`), because "what counts
    // as a good deal" is the judgement this whole app exists to make and a .qml file is
    // somewhere no test can reach it. This function only chooses the paint.
    function gradeColor(grade) {
        switch (grade) {
        case "excellent":
            return positive;
        case "good":
            return accent;
        case "fair":
            return caution;
        default:
            return negative;
        }
    }

    // Tier 0..4 → the header's intensity. Returns an alpha, so a mega sale glows and a quiet
    // Tuesday does not.
    function tierGlow(level) {
        return Math.min(0.10 + level * 0.13, 0.62);
    }
}
