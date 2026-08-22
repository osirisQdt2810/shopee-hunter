import QtQuick
import QtQuick.Effects
import Theme

/*!
    The app's one glass surface: translucent fill, hairline border, a top highlight, and an
    optional soft shadow.

    On backdrop blur — deliberately absent here. A true frosted-glass effect needs a
    ShaderEffectSource of whatever is behind each panel, resampled every frame; with a
    scrolling list of cards that is a per-item render pass and it shows on an integrated GPU.
    Instead the window itself is translucent (native vibrancy/acrylic where the OS offers it,
    see gui/window.py), and these panels are alpha over the animated background. Every panel
    therefore stays legible with no blur at all, which is the requirement.
*/
Rectangle {
    id: panel

    property real borderOpacity: 1.0
    property bool elevated: true
    property color fill: Theme.glassFill
    property color fillHover: Theme.glassFillHover
    property bool hovered: false
    property bool interactive: false

    antialiasing: true
    border.color: Qt.rgba(Theme.glassBorder.r, Theme.glassBorder.g, Theme.glassBorder.b, Theme.glassBorder.a * borderOpacity)
    border.width: Theme.borderThin
    color: interactive && hovered ? fillHover : fill
    layer.enabled: panel.elevated
    radius: Theme.radiusLg

    Behavior on color {
        ColorAnimation {
            duration: Theme.durFast
            easing.type: Theme.easeStandard
        }
    }
    layer.effect: MultiEffect {
        shadowBlur: 0.7
        shadowColor: Qt.rgba(0, 0, 0, 0.45)
        shadowEnabled: true
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 6
    }

    // The highlight along the top edge is what sells "pane of glass lit from above"; a
    // uniform border alone reads as a flat outline.
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 1
        height: 1
        radius: Theme.radiusPill
        width: parent.width - parent.radius

        gradient: Gradient {
            orientation: Gradient.Horizontal

            GradientStop {
                color: "transparent"
                position: 0.0
            }
            GradientStop {
                color: Theme.glassHighlight
                position: 0.5
            }
            GradientStop {
                color: "transparent"
                position: 1.0
            }
        }
    }
}
