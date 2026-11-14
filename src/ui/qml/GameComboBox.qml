import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: control

    font.family: Theme.bodyFont
    font.pixelSize: Theme.px(16)
    implicitHeight: Theme.px(42)
    leftPadding: Theme.px(14)
    rightPadding: Theme.px(34)

    background: BorderImage {
        opacity: control.enabled ? 0.8 : 0.4
        source: Theme.art("face-button")

        border {
            bottom: 8
            left: 10
            right: 10
            top: 8
        }
    }
    contentItem: Text {
        color: Theme.ink
        elide: Text.ElideRight
        font: control.font
        opacity: control.enabled ? 1 : 0.5
        text: control.displayText
        verticalAlignment: Text.AlignVCenter
    }
    delegate: ItemDelegate {
        required property int index

        highlighted: control.highlightedIndex === index
        width: control.width

        background: Rectangle {
            color: highlighted ? "#3b5f9b" : Theme.fieldBackground
        }
        contentItem: Text {
            color: Theme.ink
            elide: Text.ElideRight
            font: control.font
            text: control.textAt(index)
        }
    }
    indicator: Text {
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.gold
        font.pixelSize: Theme.px(20)
        text: "▾"
        x: control.width - width - Theme.px(12)
    }
    popup: Popup {
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, Theme.px(320))
        padding: Theme.px(2)
        width: control.width
        y: control.height + Theme.px(4)

        background: Rectangle {
            border.color: Theme.gold
            color: Theme.fieldBackground
        }
        contentItem: ListView {
            clip: true
            currentIndex: control.highlightedIndex
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null

            ScrollBar.vertical: GameScrollBar {
            }
        }
    }
}
