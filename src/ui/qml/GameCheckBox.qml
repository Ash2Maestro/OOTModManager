import QtQuick
import QtQuick.Controls.Basic

CheckBox {
    id: control

    font.family: Theme.bodyFont
    font.pixelSize: Theme.px(15)
    spacing: Theme.px(10)

    contentItem: Text {
        color: Theme.ink
        font: control.font
        leftPadding: control.indicator.width + control.spacing
        opacity: control.enabled ? 1 : 0.5
        text: control.text
        verticalAlignment: Text.AlignVCenter
    }
    indicator: Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        border.color: control.visualFocus || control.hovered ? Theme.ink : Theme.gold
        color: Theme.fieldBackground
        height: width
        width: Theme.px(22)
        x: control.leftPadding

        Text {
            anchors.centerIn: parent
            color: Theme.ink
            font.pixelSize: Theme.px(18)
            text: control.checked ? "✓" : ""
        }
    }
}
