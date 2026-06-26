import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A titled card grouping a set of form rows. Children declared inside a
// SectionFrame are laid out vertically in the body. Portable Controls 2.
Frame {
    id: frame
    Layout.fillWidth: true
    Layout.margins: 10

    property string title: ""
    property string subtitle: ""
    default property alias body: bodyLayout.data

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Label {
            text: frame.title
            font.bold: true
            font.pixelSize: 15
            visible: text.length > 0
        }
        Label {
            text: frame.subtitle
            color: "#888888"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            visible: text.length > 0
        }

        ColumnLayout {
            id: bodyLayout
            Layout.fillWidth: true
            spacing: 8
        }
    }
}
