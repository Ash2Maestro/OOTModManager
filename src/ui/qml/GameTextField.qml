import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control

    color: Theme.ink
    font.family: Theme.bodyFont
    font.pixelSize: Theme.px(15)
    implicitHeight: Theme.px(40)
    padding: Theme.px(10)
    selectByMouse: true
    selectedTextColor: Theme.ink
    selectionColor: "#3b5f9b"

    background: Rectangle {
        border.color: control.activeFocus ? Theme.ink : Theme.gold
        color: Theme.fieldBackground
        opacity: control.enabled ? 1 : 0.5
    }
}
