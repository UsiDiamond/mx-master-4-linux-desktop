#pragma once
#include <QWidget>

/// RadialWindow — the Actions Ring overlay window.
///
/// On Wayland (KDE Plasma 6): uses LayerShellQt to create a layer-surface
/// at the center of the screen with keyboard-interactable, above-fullscreen
/// layer.  Window type = "toolbar" (receives keyboard focus via KWin).
///
/// On X11 (LXQt / X11 sessions): uses Qt::Tool | Qt::FramelessWindowHint
/// positioned at the cursor location.  Simple WM_TYPE_NORMAL with
/// _NET_WM_WINDOW_TYPE_TOOLBAR hint is sufficient for most X11 WMs.
///
/// The QML radial menu (qml/RadialMenu.qml) is loaded into a QQuickWidget
/// embedded in this window.
///
/// The overlay is triggered by:
///   1. D-Bus signal from mx4d: org.snapdragon.MX4Daemon1.ActionRingPressed
///   2. (Debug) keyboard shortcut registered via QApplication::installEventFilter
class RadialWindow : public QWidget {
    Q_OBJECT

public:
    explicit RadialWindow(QWidget* parent = nullptr);
    ~RadialWindow() override;

    /// Show the overlay at the center of the current screen.
    void showOverlay();

    /// Hide the overlay.
    void hideOverlay();

    /// Toggle visibility.
    void toggleOverlay();

protected:
    void keyPressEvent(QKeyEvent* event) override;
    void focusOutEvent(QFocusEvent* event) override;

private:
    void setupWindow();
    void setupQml();
    void connectDaemonSignal();

    bool m_isWayland{false};
};
