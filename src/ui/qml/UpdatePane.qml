import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

OrnamentFrame {
    ScrollView {
        id: scroll

        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        anchors.fill: parent
        contentWidth: availableWidth

        ScrollBar.vertical: GameScrollBar {
        }

        ColumnLayout {
            spacing: Theme.px(18)
            width: scroll.availableWidth - Theme.px(18)

            GameCheckBox {
                id: beta

                enabled: !Manager.busy
                text: qsTr("Inclure les bêtas / préversions")
            }

            GameButton {
                enabled: !Manager.busy && !!Manager.selected.canUpdate
                text: qsTr("Vérifier sur GitHub")

                onClicked: Manager.checkUpdates(beta.checked)
            }

            Label {
                Layout.fillWidth: true
                color: Theme.muted
                text: Manager.release.message || (Manager.selected.origin === "addon" ? qsTr("Pour mettre à jour ce mod, importez son nouveau ZIP Addon. Cela met à jour la bibliothèque ; vous choisissez ensuite quand installer cette version.") : Manager.selected.canUpdate ? qsTr("Vérifiez les releases pour cette variante.") : qsTr("Aucune source de mise à jour enregistrée pour ce mod."))
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }

            Label {
                color: Theme.ink
                text: qsTr("Release : %1").arg(Manager.release.version || "")
                textFormat: Text.PlainText
                visible: !!Manager.release.version
            }

            GameButton {
                enabled: !Manager.busy && !!Manager.release.tag
                text: qsTr("Télécharger et installer")

                onClicked: Manager.installUpdate()
            }

            GameButton {
                enabled: !!Manager.release.url
                text: qsTr("Lire les changements ↗")

                onClicked: Manager.openRelease()
            }

            Label {
                Layout.fillWidth: true
                color: Theme.muted
                text: qsTr("Remplace la version active dans votre dossier de jeu.\nRomFS, sauvegardes et réglages personnels sont conservés.")
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
        }
    }
}
