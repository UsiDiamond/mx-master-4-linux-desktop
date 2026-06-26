import QtQuick
import QtQuick.Shapes

// Root overlay surface. Translucent full-window; the ring is centered. Pointer
// angle drives Radial.highlightFromAngle; release commits; Escape / outside
// click cancels. "Radial" is the RadialController context property from C++.
Rectangle {
    id: root
    color: "transparent"
    focus: true

    // Geometry of the ring.
    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real innerRadius: 72
    readonly property real outerRadius: Math.min(width, height) / 2 - 30
    // Dead-zone radius: pointer inside this targets the center hub.
    readonly property real deadZone: innerRadius

    // Open animation driver (0 -> 1).
    property real openProgress: 0.0
    NumberAnimation on openProgress {
        running: true
        from: 0.0; to: 1.0
        duration: 180
        easing.type: Easing.OutCubic
    }

    // Soft dim backdrop so the menu reads on any wallpaper. Clicking it cancels.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.28 * root.openProgress)
    }

    // The whole ring scales/fades in.
    Item {
        id: ring
        anchors.fill: parent
        opacity: root.openProgress
        scale: 0.85 + 0.15 * root.openProgress
        transformOrigin: Item.Center

        // --- segments -----------------------------------------------------
        Repeater {
            id: rep
            model: Radial.segments
            delegate: Segment {
                required property int index
                required property var modelData

                centerX: root.cx
                centerY: root.cy
                innerRadius: root.innerRadius
                outerRadius: root.outerRadius
                // Evenly spaced; segment 0 centered at 12 o'clock. Qt angles
                // are 0 deg = 3 o'clock, CW positive in screen space, so we
                // rotate by -90 and gap slightly for separation.
                property real n: rep.count
                property real gap: 3
                startAngle: (-90 - (360 / n) / 2) + index * (360 / n) + gap / 2
                sweep: (360 / n) - gap
                label: modelData.label
                iconName: modelData.icon
                highlighted: Radial.highlightedIndex === index
            }
        }

        // --- center hub ---------------------------------------------------
        Rectangle {
            id: hub
            width: root.innerRadius * 2 - 12
            height: width
            radius: width / 2
            x: root.cx - width / 2
            y: root.cy - height / 2
            color: Radial.centerHighlighted
                   ? Qt.rgba(0.20, 0.55, 0.95, 0.95)
                   : Qt.rgba(0.10, 0.11, 0.16, 0.92)
            border.color: Qt.rgba(1, 1, 1, Radial.centerHighlighted ? 0.85 : 0.25)
            border.width: Radial.centerHighlighted ? 2.5 : 1.0
            Behavior on color { ColorAnimation { duration: 120 } }

            Column {
                anchors.centerIn: parent
                spacing: 3
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 44; height: 44
                    fillMode: Image.PreserveAspectFit
                    source: Radial.centerIcon.length
                            ? ("image://theme/" + Radial.centerIcon) : ""
                    visible: status === Image.Ready
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: root.innerRadius * 2 - 24
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: Radial.centerLabel
                    color: "white"
                    font.pixelSize: 13
                    font.bold: true
                }
            }
        }
    }

    // Flick-mode hint: shown only when the ring is steered by a thumb-slide.
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 56
        visible: Radial.flickMode
        opacity: root.openProgress * 0.9
        text: "slide to aim · release to pick"
        color: "white"
        font.pixelSize: 13
        style: Text.Outline
        styleColor: Qt.rgba(0, 0, 0, 0.65)
    }

    // --- pointer tracking -------------------------------------------------
    MouseArea {
        id: tracker
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton

        function feed(px, py) {
            const dx = px - root.cx;
            const dy = py - root.cy;
            const radius = Math.sqrt(dx * dx + dy * dy);
            // Angle measured CW from 12 o'clock, in [0,360).
            let deg = Math.atan2(dx, -dy) * 180 / Math.PI;
            if (deg < 0) deg += 360;
            Radial.highlightFromAngle(deg, radius, root.deadZone);
        }

        onPositionChanged: (mouse) => feed(mouse.x, mouse.y)

        onReleased: (mouse) => {
            // A click outside the ring cancels; otherwise commit the highlight.
            const dx = mouse.x - root.cx;
            const dy = mouse.y - root.cy;
            const radius = Math.sqrt(dx * dx + dy * dy);
            if (radius > root.outerRadius + 20) {
                Radial.cancel();
            } else {
                Radial.commit();
            }
        }
    }

    // --- keyboard ---------------------------------------------------------
    Keys.onPressed: (event) => {
        switch (event.key) {
        case Qt.Key_Escape:
            Radial.cancel();
            event.accepted = true;
            break;
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Space:
            Radial.commit();
            event.accepted = true;
            break;
        case Qt.Key_Right:
        case Qt.Key_Down:
        case Qt.Key_Tab:
            Radial.highlightNext();
            event.accepted = true;
            break;
        case Qt.Key_Left:
        case Qt.Key_Up:
        case Qt.Key_Backtab:
            Radial.highlightPrev();
            event.accepted = true;
            break;
        }
    }
}
