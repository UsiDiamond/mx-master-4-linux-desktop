import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A waveform chooser: a combo of all named waveforms (supported ones plain,
// unsupported ones marked) plus a "Test" button that plays the selected one
// live through the daemon. Portable QtQuick Controls 2 only (no KF6).
RowLayout {
    id: root
    spacing: 8

    property string value: ""
    signal valueEdited(string newValue)

    // Build the display model from Config.waveformNames + Daemon support marks.
    // Recomputed whenever the daemon's capability knowledge changes.
    function displayName(name) {
        return Daemon.supportedWaveform(name)
                ? name
                : name + "  (not on this device)"
    }

    ComboBox {
        id: combo
        Layout.fillWidth: true
        model: Config.waveformNames
        Accessible.name: "Waveform"

        // Closed-combo display text: reactively re-evaluates the support mark
        // whenever the daemon's capability knowledge changes (Daemon.dummyBind
        // pulls Daemon.capabilities into the binding) or the selection moves.
        // Avoids poking the style's contentItem, which org.kde.desktop/Fusion
        // may replace or bind.
        displayText: {
            void Daemon.capabilities // dependency so this re-evaluates on change
            return root.displayName(currentText)
        }

        // Show the support mark in the popup rows.
        delegate: ItemDelegate {
            width: combo.width
            text: root.displayName(modelData)
            enabled: Daemon.supportedWaveform(modelData)
            highlighted: combo.highlightedIndex === index
        }

        function syncFromValue() {
            var idx = Config.waveformNames.indexOf(root.value)
            currentIndex = idx >= 0 ? idx : 0
        }

        Component.onCompleted: syncFromValue()
        onModelChanged: syncFromValue()

        onActivated: {
            var name = Config.waveformNames[currentIndex]
            if (name !== root.value) {
                root.value = name
                root.valueEdited(name)
            }
        }
    }

    // Keep the combo selection in step if value is set externally (e.g. load).
    onValueChanged: combo.syncFromValue()

    Button {
        text: "Test"
        Accessible.name: "Test waveform " + root.value
        ToolTip.visible: hovered
        ToolTip.text: Daemon.available
                      ? "Play this waveform on the mouse now"
                      : "Daemon not running — start it to feel the buzz"
        onClicked: Daemon.playHaptic(root.value)
    }
}
