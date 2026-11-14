import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

OrnamentFrame {
    id: page

    property string selectedId: ""
    property string selectedName: ""

    signal removalRequested(string identifier, string name)
    signal vanillaRequested

    Connections {
        function onCountChanged() {
            for (let i = 0; i < Manager.installed.count; ++i)
                if (Manager.installed.get(i).id === page.selectedId)
                    return;
            page.selectedId = "";
            page.selectedName = "";
        }

        target: Manager.installed
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.px(14)

        RowLayout {
            Layout.fillWidth: true

            Label {
                Layout.fillWidth: true
                color: Theme.ink
                font.pixelSize: Theme.px(24)
                text: qsTr("Mods installés dans ce jeu")
                textFormat: Text.PlainText
            }

            GameButton {
                enabled: !Manager.busy
                text: qsTr("Actualiser")

                onClicked: Manager.refresh()
            }
        }

        Label {
            Layout.fillWidth: true
            color: Theme.muted
            text: Manager.settings.game_dir || qsTr("Choisissez le dossier du jeu dans Paramètres.")
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
        }

        Label {
            color: Theme.muted
            text: qsTr("Aucun mod détecté.")
            textFormat: Text.PlainText
            visible: Manager.installed.count === 0
        }

        ModList {
            Layout.fillHeight: true
            Layout.fillWidth: true
            enabled: !Manager.busy
            model: Manager.installed
            selectedId: page.selectedId

            onChosen: function (identifier) {
                page.selectedId = identifier;
                for (let i = 0; i < Manager.installed.count; ++i) {
                    const row = Manager.installed.get(i);
                    if (row.id === identifier)
                        page.selectedName = row.name;
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.px(16)

            GameButton {
                enabled: !Manager.busy && !!page.selectedId
                text: qsTr("Désinstaller la sélection")

                onClicked: page.removalRequested(page.selectedId, page.selectedName)
            }

            GameButton {
                enabled: !Manager.busy
                text: qsTr("Revenir en vanilla")

                onClicked: page.vanillaRequested()
            }
        }

        Label {
            Layout.fillWidth: true
            color: Theme.muted
            text: qsTr("Désinstaller retire seulement la sélection. Vanilla restaure le programme original et désactive les mods de ressources. Sauvegardes et réglages conservés.")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
        }
    }
}
