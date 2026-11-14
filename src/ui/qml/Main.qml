import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import OOT.Backend 1.0

ApplicationWindow {
    id: window

    property int page: 0
    property bool quitAfterCancel: false
    readonly property real uiScale: Math.max(.9, Math.min(1.55, Math.min(width / 1280, height / 850)))

    function browse(key) {
        if (key === "source")
            sourceDialog.open();
        else {
            folderDialog.settingKey = key;
            folderDialog.open();
        }
    }

    function confirm(title, text, action) {
        confirmation.title = title;
        confirmation.message = text;
        confirmation.action = action;
        confirmation.open();
    }

    function confirmRemoval(identifier, name) {
        confirm(qsTr("Désinstaller un mod"), qsTr("Désinstaller « %1 » ? Les autres mods et vos sauvegardes seront conservés.").arg(name), function () {
            Manager.removeMod(identifier);
        });
    }

    // Native smoke checks exercise the same instantiated pages, without a second UI implementation.
    function runSmokeChecks() {
        if (!Manager.ready || content.width <= 0 || pages.height <= 0)
            return false;
        if (footerActions.mapToItem(window.contentItem, 0, footerActions.height).y > window.height + 1)
            return false;
        if (!library.geometryValid() || !library.translationsValid())
            return false;
        for (let i = 0; i < 3; ++i)
            window.page = i;
        window.page = 0;
        if (Manager.catalog.count > 0) {
            Manager.selectMod(Manager.catalog.get(0).id);
            library.section = "updates";
            library.section = "overview";
            if (Manager.demo) {
                Manager.applySelected();
                if (!Manager.busy)
                    return false;
                Manager.cancel();
                if (Manager.busy)
                    return false;
            }
        }
        return content.width <= window.width;
    }

    color: Theme.background
    height: 850
    minimumHeight: 720
    minimumWidth: 1060
    objectName: "managerWindow"
    title: "OOTModManager" + (Manager.demo ? qsTr(" — Démonstration") : "")
    visible: true
    width: 1280

    Component.onCompleted: Theme.scale = Qt.binding(function () {
        return window.uiScale;
    })
    onClosing: function (close) {
        if (Manager.busy) {
            if (Manager.state.action === "snapshot" || Manager.state.action === "updates") {
                Manager.cancel();
                return;
            }
            close.accepted = false;
            confirm(qsTr("Fermer le manager"), qsTr("Interrompre l’opération avant de fermer ? Le cache sera conservé."), function () {
                window.quitAfterCancel = true;
                Manager.cancel();
            });
        }
    }

    font {
        family: Theme.bodyFont
        pixelSize: Theme.px(15)
    }

    palette {
        base: "#17110b"
        button: "#60482b"
        buttonText: "#fff5df"
        highlight: "#3b5f9b"
        text: "#fff5df"
        window: "#17110b"
        windowText: "#fff5df"
    }

    Image {
        height: width * 2.04
        source: Theme.art("chronicle-tapestry")
        width: parent.width
        y: -(height - parent.height) * .3
    }

    // GPU-composited light falloff. No per-widget copies of this background.
    Rectangle {
        anchors.fill: parent
        rotation: 0

        gradient: Gradient {
            orientation: Gradient.Horizontal

            GradientStop {
                color: "#f7080603"
                position: 0
            }

            GradientStop {
                color: "#65080603"
                position: 1
            }
        }
    }

    Rectangle {
        anchors.fill: parent

        gradient: Gradient {
            GradientStop {
                color: "#d9080603"
                position: 0
            }

            GradientStop {
                color: "#08080603"
                position: 1
            }
        }
    }

    MenuHeader {
        id: header

        currentIndex: window.page
        height: Math.min(window.height * .20, width / 8.8)
        width: parent.width

        onChosen: function (index) {
            window.page = index;
        }
    }

    ColumnLayout {
        id: content

        spacing: Theme.px(12)
        width: Math.min(parent.width - Theme.px(40), Theme.px(1800))

        anchors {
            bottom: parent.bottom
            bottomMargin: Theme.px(14)
            horizontalCenter: parent.horizontalCenter
            top: header.bottom
            topMargin: Theme.px(8)
        }

        Label {
            Layout.fillWidth: true
            color: "#efc581"
            text: Manager.state.warning || ""
            textFormat: Text.PlainText
            visible: text.length > 0
            wrapMode: Text.WordWrap
        }

        StackLayout {
            id: pages

            Layout.fillHeight: true
            Layout.fillWidth: true
            Layout.minimumHeight: Theme.px(200)
            currentIndex: window.page

            LibraryPage {
                id: library

                onImportRequested: archiveDialog.open()
                onLibraryRemovalRequested: function (identifier, repository, name) {
                    window.confirm(qsTr("Supprimer de la bibliothèque"), qsTr("Supprimer « %1 » de la bibliothèque ? L'installation du jeu et les fichiers nécessaires aux préparations seront conservés. Vous pourrez réimporter son ZIP.").arg(name), function () {
                        Manager.removeLibraryEntry(identifier, repository);
                    });
                }
                onRemovalRequested: function (identifier, name) {
                    window.confirmRemoval(identifier, name);
                }
            }

            InstalledPage {
                onRemovalRequested: function (identifier, name) {
                    window.confirmRemoval(identifier, name);
                }
                onVanillaRequested: window.confirm(qsTr("Revenir en vanilla"), qsTr("Restaurer le programme original et désactiver les mods ? Sauvegardes et réglages seront conservés."), function () {
                    Manager.restoreVanilla();
                })
            }

            SettingsPage {
                onBrowse: function (key) {
                    window.browse(key);
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.px(4)
            visible: Manager.busy && Manager.ready

            Label {
                color: Theme.ink
                text: Manager.state.stage || ""
                textFormat: Text.PlainText
            }

            ProgressBar {
                Layout.fillWidth: true
                from: 0
                indeterminate: Manager.state.progress < 0
                to: 100
                value: Math.max(0, Manager.state.progress || 0)
            }

            Label {
                Layout.fillWidth: true
                color: Theme.muted
                elide: Text.ElideRight
                text: Manager.state.detail || Manager.state.plan || ""
                textFormat: Text.PlainText
            }
        }

        RowLayout {
            id: footerActions

            Layout.fillWidth: true
            spacing: Theme.px(14)

            GameButton {
                enabled: Manager.busy
                text: qsTr("Interrompre")

                onClicked: Manager.cancel()
            }

            GameButton {
                text: qsTr("Journal")

                onClicked: journal.open()
            }

            Item {
                Layout.fillWidth: true
            }

            GameButton {
                enabled: Manager.ready && !Manager.busy && !Manager.demo
                text: qsTr("Jouer  ▶")

                onClicked: Manager.play()
            }
        }
    }

    FileDialog {
        id: archiveDialog

        fileMode: FileDialog.OpenFiles
        nameFilters: [qsTr("Archives de mods (*.zip)")]
        title: qsTr("Ajouter des mods à la bibliothèque")

        onAccepted: Manager.importArchives(selectedFiles)
    }

    DropArea {
        id: archiveDrop

        anchors.fill: parent
        enabled: Manager.ready && !Manager.busy
        z: 100

        onDropped: function (drop) {
            Manager.importArchives(drop.urls);
            window.page = 0;
            drop.acceptProposedAction();
        }
        onEntered: function (drag) {
            drag.accepted = drag.hasUrls && drag.urls.length > 0 && drag.urls.length <= 32 && drag.urls.every(function (url) {
                return /\.zip$/i.test(url.toString());
            });
        }

        Rectangle {
            anchors.fill: parent
            color: "#dd100c07"
            visible: archiveDrop.containsDrag

            OrnamentFrame {
                anchors.centerIn: parent
                height: Theme.px(180)
                width: Math.min(parent.width - Theme.px(60), Theme.px(700))

                Column {
                    anchors.centerIn: parent
                    spacing: Theme.px(16)

                    Label {
                        color: Theme.ink
                        font.family: Theme.titleFont
                        font.pixelSize: Theme.px(26)
                        text: qsTr("Ajouter les ZIP à la bibliothèque")
                    }

                    Label {
                        color: Theme.muted
                        text: qsTr("Aucune installation ni compilation à cette étape.")
                    }
                }
            }
        }
    }

    FolderDialog {
        id: folderDialog

        property string settingKey

        title: qsTr("Choisir un dossier")

        onAccepted: Manager.setPath(settingKey, selectedFolder)
    }

    FileDialog {
        id: sourceDialog

        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Archive NUP (*.nup)"), qsTr("Tous les fichiers (*)")]
        title: qsTr("Choisir le jeu original")

        onAccepted: Manager.setPath("source", selectedFile)
    }

    Dialog {
        id: journal

        anchors.centerIn: Overlay.overlay
        height: Math.min(window.height - Theme.px(60), Theme.px(700))
        title: qsTr("Journal")
        width: Math.min(window.width - Theme.px(60), Theme.px(1100))

        background: Rectangle {
            border.color: Theme.gold
            color: "#17110b"
        }
        contentItem: ColumnLayout {
            ScrollView {
                Layout.fillHeight: true
                Layout.fillWidth: true

                TextArea {
                    background: null
                    color: Theme.ink
                    readOnly: true
                    text: journal.visible ? Manager.logText : ""
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere

                    font {
                        family: "Consolas"
                        pixelSize: Theme.px(13)
                    }
                }
            }

            RowLayout {
                GameButton {
                    text: qsTr("Ouvrir le fichier journal")

                    onClicked: Manager.openLog()
                }

                Item {
                    Layout.fillWidth: true
                }

                GameButton {
                    text: qsTr("Fermer")

                    onClicked: journal.close()
                }
            }
        }
    }

    Dialog {
        id: confirmation

        property var action: null
        property string message

        anchors.centerIn: Overlay.overlay
        modal: true
        width: Math.min(Theme.px(600), window.width - Theme.px(60))

        background: Rectangle {
            border.color: Theme.gold
            color: "#21170c"
        }
        contentItem: ColumnLayout {
            spacing: Theme.px(20)

            Label {
                Layout.fillWidth: true
                color: Theme.ink
                text: confirmation.message
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }

            RowLayout {
                GameButton {
                    text: qsTr("Confirmer")

                    onClicked: {
                        const action = confirmation.action;
                        confirmation.close();
                        if (action)
                            action();
                    }
                }

                GameButton {
                    text: qsTr("Annuler")

                    onClicked: confirmation.close()
                }
            }
        }
    }

    Dialog {
        id: messageDialog

        property string message

        anchors.centerIn: Overlay.overlay
        modal: true
        width: Math.min(Theme.px(720), window.width - Theme.px(60))

        background: Rectangle {
            border.color: Theme.gold
            color: "#21170c"
        }
        contentItem: ColumnLayout {
            ScrollView {
                id: messageScroll

                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(messageText.implicitHeight, window.height * .55)
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                contentWidth: availableWidth

                ScrollBar.vertical: GameScrollBar {
                }

                Label {
                    id: messageText

                    color: Theme.ink
                    text: messageDialog.message
                    textFormat: Text.PlainText
                    width: messageScroll.availableWidth - Theme.px(18)
                    wrapMode: Text.WrapAnywhere
                }
            }

            GameButton {
                text: qsTr("Fermer")

                onClicked: messageDialog.close()
            }
        }
    }

    Connections {
        function onBusyChanged() {
            if (window.quitAfterCancel && !Manager.busy)
                Qt.quit();
        }

        function onMessageRequested(title, text) {
            messageDialog.title = title;
            messageDialog.message = text;
            messageDialog.open();
        }

        target: Manager
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.background
        visible: !Manager.ready
        z: 100

        Column {
            anchors.centerIn: parent
            spacing: Theme.px(20)

            BusyIndicator {
                anchors.horizontalCenter: parent.horizontalCenter
                running: parent.visible
            }

            Label {
                color: Theme.ink
                text: qsTr("Chargement du catalogue…")
                textFormat: Text.PlainText
            }
        }
    }
}
