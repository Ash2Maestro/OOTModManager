import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

ColumnLayout {
    id: control

    property bool libraryNote: false
    property var model
    property bool searchable: false
    property string selectedId: ""

    signal chosen(string identifier)
    signal searchChanged(string query)

    function syncSelection() {
        if (!control.model)
            return;
        for (let i = 0; i < control.model.count; ++i) {
            if (control.model.get(i).id === control.selectedId) {
                list.currentIndex = i;
                list.positionViewAtIndex(i, ListView.Contain);
                return;
            }
        }
    }

    spacing: Theme.px(12)

    onSelectedIdChanged: Qt.callLater(syncSelection)

    Connections {
        function onCountChanged() {
            Qt.callLater(control.syncSelection);
        }

        target: control.model
    }

    Label {
        color: Theme.muted
        text: qsTr("Rechercher un mod")
        textFormat: Text.PlainText
        visible: control.searchable

        font {
            family: Theme.bodyFont
            pixelSize: Theme.px(14)
        }
    }

    GameTextField {
        id: search

        Layout.fillWidth: true
        color: Theme.ink
        selectionColor: "#3b5f9b"
        visible: control.searchable

        onTextEdited: control.searchChanged(text)

        font {
            family: Theme.bodyFont
            pixelSize: Theme.px(16)
        }
    }

    Item {
        id: viewport

        Layout.fillHeight: true
        Layout.fillWidth: true

        ListView {
            id: list

            anchors.fill: parent
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: Theme.px(160)
            clip: true
            flickDeceleration: 2000
            focus: true
            model: control.model
            objectName: control.searchable ? "libraryList" : "installedList"
            reuseItems: true
            spacing: Theme.px(4)

            ScrollBar.vertical: GameScrollBar {
                height: list.height
                parent: viewport
                width: Theme.px(12)
                x: 0
                y: list.y
            }
            delegate: ItemDelegate {
                id: row

                required property int index
                required property var mod
                readonly property bool selected: control.selectedId === mod.id

                height: Theme.px(76)
                hoverEnabled: true
                padding: 0
                width: ListView.view.width

                background: Item {
                    height: parent.height
                    width: parent.width - x
                    x: Theme.px(16)

                    Image {
                        anchors.fill: parent
                        source: Theme.art(row.selected ? "row-selected" : row.hovered ? "row-hover" : "row")
                    }

                    Image {
                        height: parent.height - Theme.px(10)
                        source: Theme.art(row.selected ? "row-ornament-blue" : "row-ornament")
                        width: Theme.px(15)
                        x: Theme.px(20)
                        y: Theme.px(5)
                    }

                    Rectangle {
                        color: "#f8fbff"
                        height: parent.height - Theme.px(4)
                        visible: row.selected
                        width: Theme.px(3)
                        y: Theme.px(2)
                    }
                }
                contentItem: Item {
                    Label {
                        color: Theme.ink
                        elide: Text.ElideRight
                        text: (row.mod.installed ? "✓  " : "◇  ") + row.mod.name
                        textFormat: Text.PlainText

                        anchors {
                            left: parent.left
                            leftMargin: Theme.px(64)
                            right: parent.right
                            rightMargin: Theme.px(16)
                            verticalCenter: parent.verticalCenter
                        }

                        font {
                            family: Theme.bodyFont
                            pixelSize: Theme.px(18)
                        }
                    }

                    Label {
                        color: Theme.muted
                        text: row.mod.detail || ((row.mod.origin === "addon" ? qsTr("Addon · ") : "") + (row.mod.displayVersion || row.mod.version || ""))
                        textFormat: Text.PlainText

                        anchors {
                            bottom: parent.bottom
                            margins: Theme.px(8)
                            right: parent.right
                        }

                        font {
                            family: Theme.bodyFont
                            pixelSize: Theme.px(12)
                        }
                    }
                }

                onClicked: {
                    list.currentIndex = index;
                    list.forceActiveFocus();
                    control.chosen(mod.id);
                }
            }

            Keys.onPressed: function (event) {
                if (event.key === Qt.Key_Up || event.key === Qt.Key_Down || event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                    if (event.key === Qt.Key_Up)
                        decrementCurrentIndex();
                    if (event.key === Qt.Key_Down)
                        incrementCurrentIndex();
                    if (event.key === Qt.Key_Home)
                        currentIndex = 0;
                    if (event.key === Qt.Key_End)
                        currentIndex = count - 1;
                    if (currentIndex >= 0)
                        control.chosen(control.model.get(currentIndex).id);
                    event.accepted = true;
                }
            }
        }
    }

    Label {
        Layout.fillWidth: true
        color: Theme.muted
        text: qsTr("Un pack de gameplay à la fois.\nDes packs combinés sont disponibles.")
        textFormat: Text.PlainText
        visible: control.libraryNote
        wrapMode: Text.WordWrap

        font {
            family: Theme.bodyFont
            pixelSize: Theme.px(14)
        }
    }
}
