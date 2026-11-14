import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

OrnamentFrame {
    id: page

    signal browse(string key)
    signal technicalRequested

    objectName: "settingsPage"

    ScrollView {
        id: scroll

        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        anchors.fill: parent
        contentWidth: availableWidth

        ScrollBar.vertical: GameScrollBar {
        }

        ColumnLayout {
            spacing: Theme.px(20)
            width: Math.min(scroll.availableWidth - Theme.px(18), Theme.px(1200))

            Label {
                color: Theme.ink
                font.family: Theme.titleFont
                font.pixelSize: Theme.px(32)
                text: qsTr("Paramètres")
                textFormat: Text.PlainText
            }

            Rectangle {
                Layout.fillWidth: true
                color: Theme.gold
                implicitHeight: 1
            }

            RowLayout {
                Label {
                    color: Theme.muted
                    text: qsTr("Langue de l’interface")
                }

                GameComboBox {
                    Layout.preferredWidth: Theme.px(230)
                    currentIndex: Manager.uiLanguages.findIndex(function (row) {
                        return row.code === Manager.uiLanguage;
                    })
                    enabled: !Manager.busy
                    model: Manager.uiLanguages
                    objectName: "interfaceLanguage"
                    textRole: "name"
                    valueRole: "code"

                    onActivated: Manager.setUiLanguage(currentValue)
                }
            }

            Label {
                color: Theme.ink
                font.pixelSize: Theme.px(24)
                text: qsTr("Votre jeu")
                textFormat: Text.PlainText
            }

            PathField {
                Layout.fillWidth: true
                settingKey: "game_dir"
                title: qsTr("Installation du jeu")

                onBrowse: function (key) {
                    page.browse(key);
                }
            }

            PathField {
                Layout.fillWidth: true
                settingKey: "source"
                title: qsTr("Jeu original (NUP ou dossier)")

                onBrowse: function (key) {
                    page.browse(key);
                }
            }

            GameButton {
                enabled: !Manager.busy
                text: qsTr("Enregistrer les dossiers")

                onClicked: Manager.saveSettings()
            }

            Label {
                Layout.fillWidth: true
                color: Theme.muted
                text: qsTr("Le manager applique vos mods. Les réglages du jeu restent gérés par son moteur.")
                wrapMode: Text.WordWrap
            }

            GameButton {
                text: qsTr("Paramètres techniques…")

                onClicked: page.technicalRequested()
            }
        }
    }
}
