import QtQuick
import QtQuick.Controls.Basic

ScrollBar {
    id: bar

    height: parent ? parent.height : 0
    implicitWidth: Theme.px(12)
    minimumSize: .04
    padding: Theme.px(1)
    policy: ScrollBar.AsNeeded
    visible: policy !== ScrollBar.AlwaysOff && (policy === ScrollBar.AlwaysOn || size < .999)
    x: parent ? parent.width - width : 0

    background: BorderImage {
        anchors.fill: parent
        opacity: .7
        source: Theme.art("scroll-rail")

        border {
            bottom: 14
            left: 3
            right: 3
            top: 14
        }
    }
    contentItem: Item {
        implicitHeight: Theme.px(26)
        implicitWidth: Theme.px(6)

        BorderImage {
            anchors.fill: parent
            opacity: bar.pressed ? 1 : .9
            source: Theme.art("scroll-thumb")

            // The source has transparent side margins. Stretch its full centre
            // rather than displaying only those margins in a narrow handle.
            border {
                bottom: 14
                left: 0
                right: 0
                top: 14
            }
        }
    }
}
