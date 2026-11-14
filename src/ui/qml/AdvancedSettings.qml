import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

ColumnLayout {
    id: advanced
    signal browse(string key)
    spacing: Theme.px(16)

    Label {
        Layout.fillWidth: true
        color: Theme.muted
        text: qsTr("Travail : préparations et objets de compilation (automatique si vide). Cache : builds compressés réutilisables. RomFS : ressources extraites, à renseigner uniquement si nécessaire. Bibliothèque : mods importés. Tâches : compilations en parallèle. Forcer : ignorer la réutilisation du build.")
        wrapMode: Text.WordWrap
    }

    Repeater {
        model: [
            {
                key: "workspace",
                title: qsTr("Dossier de travail et objets compilés")
            },
            {
                key: "native_cache",
                title: qsTr("Cache des builds réutilisables")
            },
            {
                key: "romfs",
                title: "RomFS"
            },
            {
                key: "mods_repo",
                title: qsTr("Dossier de la bibliothèque des mods")
            }
        ]

        delegate: PathField {
            required property var modelData

            Layout.fillWidth: true
            settingKey: modelData.key
            title: modelData.title

            onBrowse: function (key) {
                advanced.browse(key);
            }
        }
    }

    Label {
        Layout.fillWidth: true
        color: Theme.muted
        text: qsTr("Enregistrer les dossiers actualise la bibliothèque. Un dossier vide donne une bibliothèque vide ; vos mods installés restent dans le jeu.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }

    RowLayout {
        Label {
            color: Theme.muted
            text: qsTr("Tâches de compilation")
            textFormat: Text.PlainText
        }

        GameSpinBox {
            editable: true
            enabled: !Manager.busy
            from: 1
            to: 64
            value: Manager.settings.jobs || 6

            onValueModified: Manager.setSetting("jobs", value)
        }
    }

    GameCheckBox {
        checked: Manager.forceBuild
        enabled: !Manager.busy
        text: qsTr("Forcer la compilation")

        onToggled: Manager.forceBuild = checked
    }

    RowLayout {
        Label {
            color: Theme.muted
            text: qsTr("Limite du cache compressé (Mo)")
            textFormat: Text.PlainText
        }

        GameSpinBox {
            editable: true
            enabled: !Manager.busy
            from: 64
            stepSize: 256
            to: 65536
            value: Manager.settings.native_cache_limit_mib || 2048

            onValueModified: Manager.setSetting("native_cache_limit_mib", value)
        }
    }

    Label {
        Layout.fillWidth: true
        color: Theme.muted
        text: qsTr("Changer le cache utilise le nouveau dossier pour les prochaines opérations. Aucun déplacement ou effacement automatique de l’ancien cache.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
    }
}
