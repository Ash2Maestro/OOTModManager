import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects

Button {
    id: control

    focusPolicy: Qt.StrongFocus
    font.family: Theme.bodyFont
    font.pixelSize: Theme.px(16)
    horizontalPadding: Theme.px(18)
    hoverEnabled: true
    implicitHeight: Theme.px(44)
    implicitWidth: Math.max(Theme.px(120), implicitContentWidth + leftPadding + rightPadding)
    padding: Theme.px(12)

    // The source is cropped at the gold trim. No inset extends the hit rectangle.
    background: BorderImage {
        layer.enabled: control.enabled && (control.hovered || control.visualFocus)
        opacity: control.down ? .8 : 1
        source: Theme.art(control.enabled ? "face-button" : "face-button-disabled")

        layer.effect: MultiEffect {
            shadowBlur: .55
            shadowColor: "#a8cfff"
            shadowEnabled: true
            shadowHorizontalOffset: 0
            shadowOpacity: .85
            shadowVerticalOffset: 0
        }

        border {
            bottom: 8
            left: 10
            right: 10
            top: 8
        }

        Rectangle {
            anchors.fill: parent
            border.color: Theme.gold
            color: "#604521"
            visible: parent.source.toString() === ""
        }
    }
    contentItem: Text {
        color: Theme.ink
        elide: Text.ElideRight
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        opacity: control.enabled ? 1 : .45
        text: control.text
        verticalAlignment: Text.AlignVCenter
    }
}
