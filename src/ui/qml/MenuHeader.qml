import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

Item {
    id: header

    property int currentIndex: 0

    signal chosen(int index)

    Image {
        anchors.fill: parent
        fillMode: Image.Stretch
        source: Theme.art("header")
    }

    Row {
        id: tabs

        anchors.horizontalCenter: parent.horizontalCenter
        height: parent.height

        Repeater {
            model: [qsTr("Bibliothèque"), qsTr("Mods installés"), qsTr("Paramètres")]

            delegate: Button {
                id: tab

                required property int index
                required property string modelData

                height: header.height
                hoverEnabled: true
                padding: 0
                width: implicitContentWidth + Theme.px(64)

                background: Item {
                    clip: true
                    visible: header.currentIndex === tab.index

                    // Both images have exactly the same geometry/alpha contour.
                    Image {
                        height: header.height
                        source: Theme.art("header-gold")
                        width: header.width
                        x: -tab.x - tabs.x
                    }
                }
                contentItem: Text {
                    color: Theme.ink
                    horizontalAlignment: Text.AlignHCenter
                    text: tab.modelData
                    topPadding: header.height * .12

                    font {
                        family: Theme.bodyFont
                        pixelSize: Theme.px(20)
                    }
                }

                onClicked: header.chosen(index)
            }
        }
    }

    Label {
        color: Theme.muted
        text: Manager.state.status || ""
        textFormat: Text.PlainText

        anchors {
            margins: Theme.px(12)
            right: parent.right
            top: parent.top
        }

        font {
            family: Theme.bodyFont
            pixelSize: Theme.px(12)
        }
    }
}
