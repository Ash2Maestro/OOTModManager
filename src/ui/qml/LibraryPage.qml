import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

Item {
    id: page

    property string section: "overview"

    signal importRequested
    signal libraryRemovalRequested(string identifier, string repository, string name)
    signal removalRequested(string identifier, string name)

    function geometryValid() {
        return modList.width > 0 && details.width > 0 && details.x + details.width <= page.width + 1;
    }

    function translationsValid() {
        return importButton.text === qsTr("Importer des ZIP…");
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.px(24)

        ColumnLayout {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.min(Theme.px(430), Math.max(Theme.px(300), page.width * .34))
            spacing: Theme.px(12)

            GameButton {
                id: importButton

                enabled: Manager.ready && !Manager.busy
                text: qsTr("Importer des ZIP…")

                onClicked: page.importRequested()
            }

            Label {
                Layout.fillWidth: true
                color: Theme.muted
                font.pixelSize: Theme.px(13)
                text: qsTr("Ou déposez vos ZIP Addon dans la fenêtre.")
                textFormat: Text.PlainText
            }

            ModList {
                id: modList

                Layout.fillHeight: true
                Layout.fillWidth: true
                enabled: !Manager.busy
                libraryNote: true
                model: Manager.catalog
                searchable: true
                selectedId: Manager.selected.id || ""

                onChosen: function (identifier) {
                    Manager.selectMod(identifier);
                }
                onSearchChanged: function (query) {
                    Manager.filter(query);
                }
            }
        }

        ColumnLayout {
            id: details

            Layout.fillHeight: true
            Layout.fillWidth: true
            spacing: Theme.px(4)

            SubNavigation {
                Layout.fillWidth: true
                current: page.section

                onChosen: function (key) {
                    page.section = key;
                }
            }

            StackLayout {
                Layout.fillHeight: true
                Layout.fillWidth: true
                currentIndex: page.section === "updates" ? 1 : 0

                MissionCard {
                    onLibraryRemovalRequested: function (identifier, repository, name) {
                        page.libraryRemovalRequested(identifier, repository, name);
                    }
                    onRemovalRequested: function (identifier, name) {
                        page.removalRequested(identifier, name);
                    }
                }

                UpdatePane {
                }
            }
        }
    }
}
