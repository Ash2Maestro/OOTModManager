import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import OOT.Backend 1.0

ColumnLayout {
    id: control

    property string settingKey
    property string title

    signal browse(string key)

    spacing: Theme.px(6)

    Label {
        color: Theme.muted
        text: control.title
        textFormat: Text.PlainText
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.px(12)

        GameTextField {
            id: field

            Layout.fillWidth: true
            color: Theme.ink
            enabled: !Manager.busy
            selectByMouse: true
            text: Manager.settings[control.settingKey] || ""

            onTextEdited: Manager.setSetting(control.settingKey, text)
        }

        GameButton {
            enabled: !Manager.busy
            text: qsTr("Parcourir")

            onClicked: control.browse(control.settingKey)
        }
    }
}
