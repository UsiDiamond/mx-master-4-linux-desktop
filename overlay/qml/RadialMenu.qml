// RadialMenu.qml — placeholder radial overlay UI
// Full implementation: P1 — 8 evenly-spaced action sectors, center Task Manager action,
// animated open/close with haptic echo from mx4d, configurable via KCM.

import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    width: 400
    height: 400

    // Placeholder circle
    Rectangle {
        id: outerRing
        anchors.centerIn: parent
        width: 360
        height: 360
        radius: 180
        color: Qt.rgba(0.1, 0.1, 0.1, 0.85)
        border.color: "#5a7fce"
        border.width: 2

        // Centre action label (default: Task Manager)
        Text {
            anchors.centerIn: parent
            text: "Task Manager"
            color: "white"
            font.pixelSize: 16
            font.bold: true
        }
    }

    // Sector labels — 8 equally-spaced around the ring (placeholder)
    Repeater {
        model: ["App 1", "App 2", "App 3", "App 4",
                "App 5", "App 6", "App 7", "App 8"]
        delegate: Item {
            readonly property real angle: (index / 8.0) * 2 * Math.PI
            readonly property real radius: 140
            x: root.width  / 2 + radius * Math.cos(angle) - 30
            y: root.height / 2 + radius * Math.sin(angle) - 12
            width: 60
            height: 24

            Text {
                anchors.centerIn: parent
                text: modelData
                color: "#cccccc"
                font.pixelSize: 12
            }
        }
    }
}
