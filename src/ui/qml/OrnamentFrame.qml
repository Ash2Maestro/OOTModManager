import QtQuick
import QtQuick.Controls.Basic

Pane {
    id: control

    bottomPadding: Theme.px(30)
    padding: Theme.px(28)
    topPadding: Theme.px(34)

    background: Item {
        // Authored corners stay at a constant scale; only the rules stretch.
        Item {
            height: 79
            scale: Theme.scale
            transformOrigin: Item.TopLeft
            width: (parent.width - Theme.px(12)) / Theme.scale
            x: Theme.px(6)
            y: Theme.px(8)

            BorderImage {
                anchors.fill: parent
                source: Theme.art("frame")

                border {
                    bottom: 8
                    left: 24
                    right: 80
                    top: 8
                }
            }
        }

        Item {
            height: 79
            scale: Theme.scale
            transformOrigin: Item.TopLeft
            width: (parent.width - Theme.px(12)) / Theme.scale
            x: Theme.px(6)
            y: parent.height - Theme.px(87)

            BorderImage {
                anchors.fill: parent
                rotation: 180
                source: Theme.art("frame")

                border {
                    bottom: 8
                    left: 24
                    right: 80
                    top: 8
                }
            }
        }
    }
}
