import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

OrnamentFrame {
    id: card

    signal libraryRemovalRequested(string identifier, string repository, string name)
    signal removalRequested(string identifier, string name)

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.px(16)

        Label {
            Layout.fillWidth: true
            color: Theme.ink
            text: Manager.selected.title || qsTr("Choisissez un mod")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap

            font {
                family: Theme.titleFont
                pixelSize: Theme.px(32)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            color: Theme.gold
            implicitHeight: 1
        }

        Label {
            Layout.fillWidth: true
            color: Theme.muted
            font.pixelSize: Theme.px(13)
            text: qsTr("Archive importée : ") + (Manager.selected.archiveName || "")
            textFormat: Text.PlainText
            visible: Manager.selected.origin === "addon"
            wrapMode: Text.WrapAnywhere
        }

        ScrollView {
            id: descriptionScroll

            Layout.fillHeight: true
            Layout.fillWidth: true
            Layout.minimumHeight: Theme.px(50)
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            contentWidth: availableWidth

            ScrollBar.vertical: GameScrollBar {
            }

            ColumnLayout {
                spacing: Theme.px(14)
                width: descriptionScroll.availableWidth - Theme.px(18)

                Label {
                    Layout.fillWidth: true
                    color: Theme.muted
                    text: Manager.selected.subtitle || ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                }

                Label {
                    Layout.fillWidth: true
                    color: Theme.ink
                    text: Manager.selected.description || (Manager.selected.id ? qsTr("Aucune description fournie dans cet Addon.") : qsTr("Importez un ZIP Addon pour afficher sa fiche."))
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                }

                Label {
                    Layout.fillWidth: true
                    color: Theme.muted
                    text: qsTr("Auteur : %1").arg(Manager.selected.author || "")
                    textFormat: Text.PlainText
                    visible: !!Manager.selected.author
                    wrapMode: Text.WordWrap
                }

                Label {
                    Layout.fillWidth: true
                    color: Theme.muted
                    font.pixelSize: Theme.px(13)
                    text: (Manager.selected.contentSummary || "") + "\n" + (Manager.selected.presentationSource || "")
                    textFormat: Text.PlainText
                    visible: !!Manager.selected.id
                    wrapMode: Text.WordWrap
                }

                Label {
                    color: Theme.gold
                    text: qsTr("DANS VOTRE JEU")
                    textFormat: Text.PlainText
                }

                Label {
                    Layout.fillWidth: true
                    color: Theme.muted
                    text: qsTr("Actuellement : %1").arg(Manager.state.activeName || qsTr("Jeu original"))
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                }

                Label {
                    color: Theme.gold
                    text: qsTr("À SAVOIR")
                    textFormat: Text.PlainText
                }

                Label {
                    Layout.fillWidth: true
                    color: Theme.muted
                    text: Manager.selected.kind === "romfs" ? qsTr("Addon de ressources : installation sans compilation. Les conflits de fichiers sont vérifiés.") : qsTr("Un seul pack de gameplay peut être actif. Installer ce mod remplace le pack précédent. Vos sauvegardes sont conservées.")
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.px(14)

            GameButton {
                enabled: Manager.ready && !Manager.busy && !!Manager.selected.id
                objectName: "installModButton"
                text: Manager.selected.installed ? qsTr("Réappliquer ce mod") : qsTr("Installer ce mod")

                onClicked: Manager.applySelected()
            }

            GameButton {
                enabled: !Manager.busy
                text: qsTr("Désinstaller ce mod")
                visible: !!Manager.selected.installed

                onClicked: card.removalRequested(Manager.selected.removalId || "native:" + Manager.selected.id, Manager.selected.name)
            }

            GameButton {
                enabled: Manager.ready && !Manager.busy
                objectName: "removeLibraryButton"
                text: qsTr("Supprimer de la bibliothèque")
                visible: !!Manager.selected.id

                onClicked: card.libraryRemovalRequested(Manager.selected.id, Manager.selected.repository, Manager.selected.name)
            }
        }
    }
}
