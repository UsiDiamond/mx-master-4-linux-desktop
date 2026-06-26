import QtQuick

// MPRIS media-controls panel (the press-and-hold overlay). Shows the active
// player's art + title/artist, transport buttons, and a seek bar. "Media" is
// the MprisController context property from C++. Click-outside / Escape closes.
Rectangle {
    id: root
    color: "transparent"
    focus: true

    property real openProgress: 0.0
    NumberAnimation on openProgress {
        running: true
        from: 0.0; to: 1.0
        duration: 160
        easing.type: Easing.OutCubic
    }

    // mm:ss from MPRIS microseconds.
    function fmt(us) {
        if (us <= 0) return "0:00";
        const s = Math.floor(us / 1000000);
        const m = Math.floor(s / 60);
        const r = s % 60;
        return m + ":" + (r < 10 ? "0" + r : r);
    }

    // Dim backdrop; clicking it (outside the card) closes the panel.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.30 * root.openProgress)
        MouseArea { anchors.fill: parent; onClicked: Media.dismiss() }
    }

    // The card.
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(root.width - 24, 560)
        height: Math.min(root.height - 24, 232)
        radius: 18
        color: Qt.rgba(0.10, 0.11, 0.16, 0.96)
        border.color: Qt.rgba(1, 1, 1, 0.12)
        border.width: 1
        opacity: root.openProgress
        scale: 0.94 + 0.06 * root.openProgress
        // Absorb clicks so they don't fall through to the dismiss backdrop.
        MouseArea { anchors.fill: parent }

        // --- Album art (left) ---------------------------------------------
        Rectangle {
            id: artBox
            width: 168; height: 168
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            radius: 12
            color: Qt.rgba(1, 1, 1, 0.06)
            clip: true

            Image {
                id: art
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                cache: false
                asynchronous: true
                source: Media.available && Media.artUrl.length ? Media.artUrl : ""
                visible: status === Image.Ready
            }
            // Fallback glyph when there is no art (or it failed to load).
            Image {
                anchors.centerIn: parent
                width: 72; height: 72
                fillMode: Image.PreserveAspectFit
                source: "image://theme/audio-x-generic"
                visible: art.status !== Image.Ready
                opacity: 0.7
            }
        }

        // --- Right column: text, transport, seek --------------------------
        Item {
            anchors.left: artBox.right
            anchors.leftMargin: 18
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            height: 168

            // Title + artist (or a "nothing playing" line).
            Text {
                id: titleText
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                elide: Text.ElideRight
                text: Media.available
                      ? (Media.title.length ? Media.title : "Unknown title")
                      : "Nothing playing"
                color: "white"
                font.pixelSize: 19
                font.bold: true
            }
            Text {
                id: artistText
                anchors.top: titleText.bottom
                anchors.topMargin: 3
                anchors.left: parent.left
                anchors.right: parent.right
                elide: Text.ElideRight
                text: Media.available
                      ? (Media.artist.length ? Media.artist : Media.playerName)
                      : "Start playing something to control it here"
                color: Qt.rgba(1, 1, 1, 0.7)
                font.pixelSize: 14
            }

            // Transport row.
            Row {
                id: transport
                anchors.top: artistText.bottom
                anchors.topMargin: 18
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 22

                // A round icon button.
                component CtrlButton: Item {
                    property alias icon: img.source
                    property bool enabled: true
                    property real diameter: 44
                    signal clicked()
                    width: diameter; height: diameter
                    opacity: enabled ? 1.0 : 0.35
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: tap.pressed ? Qt.rgba(0.20, 0.55, 0.95, 0.95)
                                           : Qt.rgba(1, 1, 1, 0.08)
                    }
                    Image {
                        id: img
                        anchors.centerIn: parent
                        width: parent.diameter * 0.55
                        height: width
                        fillMode: Image.PreserveAspectFit
                    }
                    MouseArea {
                        id: tap
                        anchors.fill: parent
                        enabled: parent.enabled
                        onClicked: parent.clicked()
                    }
                }

                CtrlButton {
                    icon: "image://theme/media-skip-backward"
                    enabled: Media.available && Media.canGoPrevious
                    onClicked: Media.previous()
                }
                CtrlButton {
                    diameter: 56
                    icon: Media.playing ? "image://theme/media-playback-pause"
                                        : "image://theme/media-playback-start"
                    enabled: Media.available
                    onClicked: Media.playPause()
                }
                CtrlButton {
                    icon: "image://theme/media-skip-forward"
                    enabled: Media.available && Media.canGoNext
                    onClicked: Media.next()
                }
            }

            // Seek bar + time labels.
            Item {
                id: seek
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 34
                visible: Media.available

                // Local drag preview fraction (>=0 while mouse-dragging), else -1.
                // A thumb seek-scrub (Media.scrubbing) takes precedence and
                // draws the bar at the previewed position.
                property real dragFrac: -1
                property real frac: Media.scrubbing
                    ? (Media.length > 0 ? Media.scrubPosition / Media.length : 0)
                    : (dragFrac >= 0
                        ? dragFrac
                        : (Media.length > 0 ? Media.position / Media.length : 0))

                Text {
                    id: posLabel
                    anchors.left: parent.left
                    anchors.verticalCenter: track.verticalCenter
                    text: root.fmt(Media.scrubbing
                                   ? Media.scrubPosition
                                   : (seek.dragFrac >= 0 ? seek.dragFrac * Media.length
                                                         : Media.position))
                    color: Media.scrubbing ? Qt.rgba(0.40, 0.70, 1.0, 0.95)
                                           : Qt.rgba(1, 1, 1, 0.75)
                    font.pixelSize: 12
                    font.bold: Media.scrubbing
                }
                Text {
                    id: lenLabel
                    anchors.right: parent.right
                    anchors.verticalCenter: track.verticalCenter
                    text: root.fmt(Media.length)
                    color: Qt.rgba(1, 1, 1, 0.75)
                    font.pixelSize: 12
                }

                Rectangle {
                    id: track
                    anchors.left: posLabel.right
                    anchors.right: lenLabel.left
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    height: 6
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.16)

                    Rectangle { // filled portion
                        height: parent.height
                        radius: parent.radius
                        width: parent.width * Math.max(0, Math.min(1, seek.frac))
                        color: Qt.rgba(0.20, 0.55, 0.95, 0.95)
                    }
                    Rectangle { // handle
                        width: 14; height: 14; radius: 7
                        color: "white"
                        y: (parent.height - height) / 2
                        x: parent.width * Math.max(0, Math.min(1, seek.frac)) - width / 2
                        visible: Media.canSeek
                    }
                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -8 // easier to grab
                        enabled: Media.canSeek && Media.length > 0
                        function fracAt(mx) {
                            return Math.max(0, Math.min(1, mx / track.width));
                        }
                        onPressed: (m) => seek.dragFrac = fracAt(m.x)
                        onPositionChanged: (m) => { if (pressed) seek.dragFrac = fracAt(m.x); }
                        onReleased: (m) => {
                            const f = fracAt(m.x);
                            Media.seekTo(Math.round(f * Media.length));
                            seek.dragFrac = -1;
                        }
                    }
                }
            }
        }
    }

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Escape) {
            Media.dismiss();
            event.accepted = true;
        }
    }
}
