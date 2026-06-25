import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

// MX Master 4 settings window. Portable QtQuick Controls 2 (works on Plasma 6
// and LXQt, no KF6). "Config" is the C++ ConfigModel, "Daemon" the DaemonBridge.
ApplicationWindow {
    id: win
    visible: true
    width: 760
    height: 720
    minimumWidth: 560
    minimumHeight: 480
    title: qsTr("MX Master 4 Settings") + (Config.dirty ? " •" : "")

    // ---- top bar: daemon status + a hint when absent ----------------------
    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 10

            Label {
                text: qsTr("MX Master 4 Settings")
                font.bold: true
                font.pixelSize: 16
                Layout.fillWidth: true
            }

            // Live daemon presence dot + label.
            Rectangle {
                width: 10; height: 10; radius: 5
                color: Daemon.available ? "#2ecc71" : "#bbbbbb"
            }
            Label {
                text: Daemon.available
                      ? qsTr("daemon connected")
                      : qsTr("daemon not running")
                color: Daemon.available ? palette.text : "#888888"
                ToolTip.visible: hoverHandler.hovered
                ToolTip.text: Daemon.available
                    ? qsTr("Live waveform preview is available.")
                    : qsTr("Start the daemon (mx4d) to feel waveform previews. Settings still save.")
                HoverHandler { id: hoverHandler }
            }
        }
    }

    // ---- the scrolling form ----------------------------------------------
    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 0
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0

            // ====================================================== Ambient
            SectionFrame {
                title: qsTr("Ambient haptics")
                subtitle: qsTr("Buzz the mouse on desktop events.")

                Switch {
                    text: qsTr("Enable ambient haptics")
                    checked: Config.ambientEnabled
                    Accessible.name: text
                    onToggled: Config.ambientEnabled = checked
                }
                Switch {
                    text: qsTr("Quiet hours (suppress ambient buzzes)")
                    checked: Config.quietHours
                    enabled: Config.ambientEnabled
                    Accessible.name: text
                    onToggled: Config.quietHours = checked
                }

                RowLayout {
                    Layout.fillWidth: true
                    enabled: Config.ambientEnabled
                    Label {
                        text: qsTr("Debounce interval")
                        Layout.preferredWidth: 160
                    }
                    Slider {
                        id: debounceSlider
                        Layout.fillWidth: true
                        from: 0.0; to: 1.0; stepSize: 0.01
                        value: Config.debounceInterval
                        Accessible.name: qsTr("Debounce interval seconds")
                        onMoved: Config.debounceInterval = value
                    }
                    Label {
                        text: Config.debounceInterval.toFixed(2) + " s"
                        Layout.preferredWidth: 60
                    }
                }

                MenuSeparator { Layout.fillWidth: true }

                Label {
                    text: qsTr("Per-source")
                    font.bold: true
                }

                // notification / focus / sound rows from Config.sources.
                Repeater {
                    model: Config.sources
                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        required property var modelData
                        readonly property string kind: modelData.kind
                        enabled: Config.ambientEnabled

                        RowLayout {
                            Layout.fillWidth: true
                            Switch {
                                text: kind.charAt(0).toUpperCase() + kind.slice(1)
                                checked: modelData.enabled
                                Accessible.name: qsTr("Enable %1 haptics").arg(kind)
                                onToggled: Config.setSourceEnabled(kind, checked)
                                Layout.preferredWidth: 160
                            }
                            WaveformPicker {
                                Layout.fillWidth: true
                                enabled: modelData.enabled
                                value: modelData.waveform
                                onValueEdited: (v) => Config.setSourceWaveform(kind, v)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 24
                            enabled: modelData.enabled
                            Label {
                                text: qsTr("Intensity")
                                Layout.preferredWidth: 136
                            }
                            Slider {
                                Layout.fillWidth: true
                                from: 0; to: 100; stepSize: 1
                                value: modelData.intensity
                                Accessible.name: qsTr("%1 intensity").arg(kind)
                                onMoved: Config.setSourceIntensity(kind, Math.round(value))
                            }
                            Label {
                                text: modelData.intensity
                                Layout.preferredWidth: 36
                            }
                        }
                    }
                }
            }

            // ====================================================== Haptics
            SectionFrame {
                title: qsTr("Haptics")
                subtitle: qsTr("Global motor strength (applied live when the daemon runs).")

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Global level")
                        Layout.preferredWidth: 160
                    }
                    Slider {
                        Layout.fillWidth: true
                        from: 0; to: 100; stepSize: 1
                        value: Config.hapticLevel
                        Accessible.name: qsTr("Global haptic level")
                        onMoved: {
                            Config.hapticLevel = Math.round(value)
                            Daemon.setLevel(Config.hapticLevel) // live
                        }
                    }
                    Label {
                        text: Config.hapticLevel
                        Layout.preferredWidth: 36
                    }
                }
            }

            // ====================================================== Trigger
            SectionFrame {
                title: qsTr("Actions Ring trigger")
                subtitle: qsTr("The haptic touch panel that summons the radial menu.")

                Switch {
                    text: qsTr("Divert the Actions Ring panel for capture")
                    checked: Config.divertPanel
                    Accessible.name: text
                    onToggled: Config.divertPanel = checked
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Press waveform")
                        Layout.preferredWidth: 160
                    }
                    WaveformPicker {
                        Layout.fillWidth: true
                        value: Config.triggerWaveform
                        onValueEdited: (v) => Config.triggerWaveform = v
                    }
                }
            }

            // ====================================================== Radial menu
            SectionFrame {
                title: qsTr("Radial menu")
                subtitle: qsTr("The Actions Ring center action and segments.")

                Label { text: qsTr("Center action"); font.bold: true }
                GridLayout {
                    columns: 2
                    Layout.fillWidth: true
                    columnSpacing: 10
                    rowSpacing: 6

                    Label { text: qsTr("Label") }
                    TextField {
                        Layout.fillWidth: true
                        text: Config.centerLabel
                        Accessible.name: qsTr("Center label")
                        onEditingFinished: Config.centerLabel = text
                    }
                    Label { text: qsTr("Icon name") }
                    TextField {
                        Layout.fillWidth: true
                        text: Config.centerIcon
                        Accessible.name: qsTr("Center icon name")
                        onEditingFinished: Config.centerIcon = text
                    }
                    Label { text: qsTr("Command") }
                    TextField {
                        Layout.fillWidth: true
                        text: Config.centerCommand
                        placeholderText: qsTr("e.g. plasma-systemmonitor (no shell)")
                        Accessible.name: qsTr("Center command")
                        onEditingFinished: Config.centerCommand = text
                    }
                    Label { text: qsTr("Default menu id") }
                    TextField {
                        Layout.fillWidth: true
                        text: Config.defaultMenu
                        Accessible.name: qsTr("Default menu id")
                        onEditingFinished: Config.defaultMenu = text
                    }
                }

                MenuSeparator { Layout.fillWidth: true }

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Segments (%1)").arg(Config.segments.length)
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    Button {
                        text: qsTr("Add segment")
                        Accessible.name: text
                        onClicked: Config.addSegment()
                    }
                }

                Repeater {
                    model: Config.segments
                    delegate: Frame {
                        Layout.fillWidth: true
                        required property var modelData
                        required property int index

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: qsTr("#%1").arg(index + 1)
                                    font.bold: true
                                }
                                Item { Layout.fillWidth: true }
                                Button {
                                    text: "↑"
                                    enabled: index > 0
                                    Accessible.name: qsTr("Move segment up")
                                    onClicked: Config.moveSegment(index, index - 1)
                                }
                                Button {
                                    text: "↓"
                                    enabled: index < Config.segments.length - 1
                                    Accessible.name: qsTr("Move segment down")
                                    onClicked: Config.moveSegment(index, index + 1)
                                }
                                Button {
                                    text: qsTr("Remove")
                                    Accessible.name: qsTr("Remove segment %1").arg(index + 1)
                                    onClicked: Config.removeSegment(index)
                                }
                            }

                            GridLayout {
                                columns: 4
                                Layout.fillWidth: true
                                columnSpacing: 8
                                rowSpacing: 6

                                Label { text: qsTr("Label") }
                                TextField {
                                    Layout.fillWidth: true
                                    text: modelData.label
                                    Accessible.name: qsTr("Segment %1 label").arg(index + 1)
                                    onEditingFinished: Config.setSegmentField(index, "label", text)
                                }
                                Label { text: qsTr("Id") }
                                TextField {
                                    Layout.fillWidth: true
                                    text: modelData.id
                                    Accessible.name: qsTr("Segment %1 id").arg(index + 1)
                                    onEditingFinished: Config.setSegmentField(index, "id", text)
                                }

                                Label { text: qsTr("Icon") }
                                TextField {
                                    Layout.fillWidth: true
                                    text: modelData.icon
                                    Accessible.name: qsTr("Segment %1 icon").arg(index + 1)
                                    onEditingFinished: Config.setSegmentField(index, "icon", text)
                                }
                                Label { text: qsTr("Type") }
                                ComboBox {
                                    Layout.fillWidth: true
                                    model: ["command", "noop"]
                                    Accessible.name: qsTr("Segment %1 action type").arg(index + 1)
                                    currentIndex: modelData.actionType === "noop" ? 1 : 0
                                    onActivated: Config.setSegmentField(index, "actionType",
                                                                        model[currentIndex])
                                }

                                Label { text: qsTr("Command") }
                                TextField {
                                    Layout.columnSpan: 3
                                    Layout.fillWidth: true
                                    enabled: modelData.actionType !== "noop"
                                    text: modelData.command
                                    placeholderText: qsTr("argv, quote-aware split, NO shell")
                                    Accessible.name: qsTr("Segment %1 command").arg(index + 1)
                                    onEditingFinished: Config.setSegmentField(index, "command", text)
                                }
                            }
                        }
                    }
                }
            }

            // ====================================================== Overlay
            SectionFrame {
                title: qsTr("Overlay")
                subtitle: qsTr("How the daemon launches the radial menu process.")

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: qsTr("Launch command")
                        Layout.preferredWidth: 160
                    }
                    TextField {
                        Layout.fillWidth: true
                        text: Config.overlayCommand
                        Accessible.name: qsTr("Overlay launch command")
                        onEditingFinished: Config.overlayCommand = text
                    }
                }
            }

            Item { Layout.preferredHeight: 12 } // bottom breathing room
        }
    }

    // ---- footer: dirty state + Apply / Revert -----------------------------
    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            Label {
                text: Config.dirty ? qsTr("Unsaved changes")
                                   : qsTr("All changes saved")
                color: Config.dirty ? "#e67e22" : "#888888"
                Layout.fillWidth: true
            }
            Button {
                text: qsTr("Revert")
                enabled: Config.dirty
                Accessible.name: text
                onClicked: Config.revert()
            }
            Button {
                text: qsTr("Apply")
                enabled: Config.dirty
                highlighted: true
                Accessible.name: qsTr("Apply and save settings")
                onClicked: {
                    if (!Config.save()) {
                        saveError.open()
                    }
                }
            }
        }
    }

    // Confirm-on-close if there are unsaved edits.
    onClosing: (close) => {
        if (Config.dirty) {
            close.accepted = false
            closeDialog.open()
        }
    }

    Dialog {
        id: closeDialog
        anchors.centerIn: parent
        title: qsTr("Unsaved changes")
        standardButtons: Dialog.Save | Dialog.Discard | Dialog.Cancel
        modal: true
        Label { text: qsTr("Save your changes before closing?") }
        onAccepted: { Config.save(); win.close() }   // Save
        onDiscarded: { Config.revert(); win.close() } // Discard
    }

    Dialog {
        id: saveError
        anchors.centerIn: parent
        title: qsTr("Could not save")
        standardButtons: Dialog.Ok
        modal: true
        Label { text: qsTr("Writing the config file failed. Check permissions on\n%1").arg(Config.configPath) }
    }
}
