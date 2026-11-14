pragma Singleton
import QtQuick
import OOT.Backend 1.0

QtObject {
    readonly property color background: "#100c07"
    readonly property string bodyFont: Manager.bodyFont
    readonly property color fieldBackground: "#c9171008"
    readonly property color gold: "#bb8a56"
    readonly property color ink: "#fff5df"
    readonly property color muted: "#cbb793"
    property real scale: 1
    readonly property string titleFont: Manager.titleFont

    function art(name) {
        return Manager.assetsReady ? "image://art/" + name + "?v=" + Manager.assetRevision : "";
    }

    function px(value) {
        return value * scale;
    }
}
