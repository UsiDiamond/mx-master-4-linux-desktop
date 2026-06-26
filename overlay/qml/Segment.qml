import QtQuick
import QtQuick.Shapes

// One ring segment: a filled annular wedge (Shape + PathAngleArc) plus an
// icon and label positioned at its angular center. Highlight is animated.
Item {
    id: seg
    anchors.fill: parent

    // --- inputs -----------------------------------------------------------
    property real centerX: width / 2
    property real centerY: height / 2
    property real innerRadius: 70
    property real outerRadius: 230
    property real startAngle: 0   // degrees, 0 = 3 o'clock (Qt convention)
    property real sweep: 60        // degrees
    property bool highlighted: false
    property string label: ""
    property string iconName: ""

    // Color scheme (translucent, looks clean on transparent bg).
    readonly property color baseColor: Qt.rgba(0.12, 0.13, 0.18, 0.82)
    readonly property color hiColor: Qt.rgba(0.20, 0.55, 0.95, 0.92)

    // Mid-angle of this wedge, used to place the icon/label.
    readonly property real midDeg: startAngle + sweep / 2
    readonly property real midRad: midDeg * Math.PI / 180.0
    readonly property real labelRadius: (innerRadius + outerRadius) / 2

    Shape {
        anchors.fill: parent
        asynchronous: false
        preferredRendererType: Shape.GeometryRenderer

        ShapePath {
            id: wedge
            fillColor: seg.highlighted ? seg.hiColor : seg.baseColor
            strokeColor: Qt.rgba(1, 1, 1, seg.highlighted ? 0.85 : 0.18)
            strokeWidth: seg.highlighted ? 2.5 : 1.0
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            // Outer arc start point.
            startX: seg.centerX + seg.outerRadius * Math.cos(seg.startAngle * Math.PI / 180)
            startY: seg.centerY + seg.outerRadius * Math.sin(seg.startAngle * Math.PI / 180)

            // Outer arc sweep.
            PathAngleArc {
                centerX: seg.centerX
                centerY: seg.centerY
                radiusX: seg.outerRadius
                radiusY: seg.outerRadius
                startAngle: seg.startAngle
                sweepAngle: seg.sweep
            }
            // Line in to the inner radius at the end angle.
            PathLine {
                x: seg.centerX + seg.innerRadius * Math.cos((seg.startAngle + seg.sweep) * Math.PI / 180)
                y: seg.centerY + seg.innerRadius * Math.sin((seg.startAngle + seg.sweep) * Math.PI / 180)
            }
            // Inner arc back the other way.
            PathAngleArc {
                centerX: seg.centerX
                centerY: seg.centerY
                radiusX: seg.innerRadius
                radiusY: seg.innerRadius
                startAngle: seg.startAngle + seg.sweep
                sweepAngle: -seg.sweep
            }
            // Close back to the start.
            PathLine {
                x: seg.centerX + seg.outerRadius * Math.cos(seg.startAngle * Math.PI / 180)
                y: seg.centerY + seg.outerRadius * Math.sin(seg.startAngle * Math.PI / 180)
            }

            Behavior on fillColor { ColorAnimation { duration: 120 } }
            Behavior on strokeWidth { NumberAnimation { duration: 120 } }
        }
    }

    // Icon + label at the wedge mid-angle.
    Column {
        spacing: 4
        width: 96
        x: seg.centerX + seg.labelRadius * Math.cos(seg.midRad) - width / 2
        y: seg.centerY + seg.labelRadius * Math.sin(seg.midRad) - height / 2
        scale: seg.highlighted ? 1.12 : 1.0
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutBack } }

        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 40; height: 40
            fillMode: Image.PreserveAspectFit
            // Theme icon by name; missing icons resolve to nothing (no crash).
            source: seg.iconName.length ? ("image://theme/" + seg.iconName) : ""
            visible: status === Image.Ready
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 92
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: seg.label
            color: "white"
            font.pixelSize: 13
            font.bold: seg.highlighted
        }
    }
}
