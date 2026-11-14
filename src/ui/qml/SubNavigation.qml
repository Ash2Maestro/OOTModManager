import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Effects

Item {
    id: navigation

    property string current: "overview"

    signal chosen(string key)

    implicitHeight: Theme.px(50)

    RowLayout {
        anchors.centerIn: parent
        spacing: Theme.px(12)

        Repeater {
            model: [
                {
                    key: "overview",
                    title: qsTr("Présentation")
                },
                {
                    key: "updates",
                    title: qsTr("Mises à jour")
                }
            ]

            delegate: Button {
                id: tab

                required property var modelData
                readonly property bool selected: navigation.current === modelData.key

                horizontalPadding: Theme.px(26)
                hoverEnabled: true
                padding: Theme.px(8)
                text: modelData.title

                background: Item {
                    visible: tab.selected

                    Image {
                        height: width
                        source: Theme.art("title-ornament")
                        width: Theme.px(20)

                        anchors {
                            left: parent.left
                            verticalCenter: parent.verticalCenter
                        }
                    }

                    Image {
                        height: width
                        mirror: true
                        source: Theme.art("title-ornament")
                        width: Theme.px(20)

                        anchors {
                            right: parent.right
                            verticalCenter: parent.verticalCenter
                        }
                    }
                }
                contentItem: Text {
                    color: Theme.ink
                    layer.enabled: tab.selected || tab.hovered || tab.visualFocus
                    text: tab.text

                    layer.effect: MultiEffect {
                        shadowBlur: .8
                        shadowColor: "#9bb3ff"
                        shadowEnabled: true
                        shadowHorizontalOffset: 0
                        shadowOpacity: 1
                        shadowVerticalOffset: 0
                    }

                    font {
                        family: Theme.bodyFont
                        pixelSize: Theme.px(18)
                    }
                }

                onClicked: navigation.chosen(modelData.key)
            }
        }
    }
}
