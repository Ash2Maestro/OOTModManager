import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

Dialog {
    id: dialog

    signal browse(string key)

    anchors.centerIn: Overlay.overlay
    height: Math.min(parent.height - Theme.px(60), Theme.px(760))
    modal: true
    padding: Theme.px(30)
    title: qsTr("Paramètres techniques")
    width: Math.min(parent.width - Theme.px(60), Theme.px(950))

    background: Item {
        Rectangle {
            anchors.fill: parent
            color: "#ee100c07"
        }

        OrnamentFrame {
            anchors.fill: parent
        }
    }
    contentItem: ColumnLayout {
        ScrollView {
            id: scroll

            Layout.fillHeight: true
            Layout.fillWidth: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            contentWidth: availableWidth

            ScrollBar.vertical: GameScrollBar {
            }

            ColumnLayout {
                spacing: Theme.px(16)
                width: scroll.availableWidth - Theme.px(18)

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
                            key: "tools_path",
                            title: qsTr("Outils du moteur")
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
                            dialog.browse(key);
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
        }

        RowLayout {
            GameButton {
                enabled: !Manager.busy
                text: qsTr("Enregistrer les dossiers")

                onClicked: {
                    Manager.saveSettings();
                    dialog.close();
                }
            }

            Item {
                Layout.fillWidth: true
            }

            GameButton {
                text: qsTr("Fermer")

                onClicked: dialog.close()
            }
        }
    }
    header: Label {
        bottomPadding: Theme.px(12)
        color: Theme.ink
        font.family: Theme.titleFont
        font.pixelSize: Theme.px(28)
        padding: Theme.px(32)
        text: dialog.title
    }
}
