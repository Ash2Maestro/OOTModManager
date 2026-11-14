import QtQuick
import QtQuick.Controls.Basic

SpinBox {
    id: control

    font.family: Theme.bodyFont
    font.pixelSize: Theme.px(15)
    implicitHeight: Theme.px(40)
    implicitWidth: Theme.px(150)
    palette.base: Theme.fieldBackground
    palette.button: "#60482b"
    palette.buttonText: Theme.ink
    palette.text: Theme.ink

    background: Rectangle {
        border.color: control.activeFocus ? Theme.ink : Theme.gold
        color: Theme.fieldBackground
    }
}
