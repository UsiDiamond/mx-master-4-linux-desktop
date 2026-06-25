#include "radial_window.h"

#include <QApplication>
#include <QDBusConnection>
#include <QFocusEvent>
#include <QKeyEvent>
#include <QScreen>
#include <QVBoxLayout>
#include <QLabel>

// ---------------------------------------------------------------------------

RadialWindow::RadialWindow(QWidget* parent)
    : QWidget(parent)
{
    // Detect session type
    const QByteArray sessionType = qgetenv("XDG_SESSION_TYPE");
    m_isWayland = (sessionType == "wayland");

    setupWindow();
    connectDaemonSignal();
}

RadialWindow::~RadialWindow() = default;

// ---------------------------------------------------------------------------

void RadialWindow::setupWindow()
{
    if (m_isWayland) {
        // Wayland: LayerShellQt integration will be wired in a follow-up commit.
        // For now, use a frameless top-level with a translucent background as a
        // placeholder that still renders correctly in XWayland.
        setWindowFlags(Qt::Window | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    } else {
        // X11: Tool window, frameless, always-on-top
        setWindowFlags(Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    }

    setAttribute(Qt::WA_TranslucentBackground);
    setFocusPolicy(Qt::StrongFocus);
    resize(400, 400);

    // Placeholder UI — replaced by QML in the next increment
    auto* layout = new QVBoxLayout(this);
    auto* label  = new QLabel(QStringLiteral("MX4 Actions Ring\n[placeholder]"), this);
    label->setAlignment(Qt::AlignCenter);
    label->setStyleSheet(QStringLiteral(
        "color: white; background: rgba(20,20,20,200); border-radius: 200px;"
        "font-size: 18px; padding: 40px;"));
    layout->addWidget(label);
}

void RadialWindow::connectDaemonSignal()
{
    // Listen for the D-Bus signal from mx4d
    QDBusConnection::sessionBus().connect(
        QStringLiteral("org.snapdragon.MX4Daemon1"),
        QStringLiteral("/"),
        QStringLiteral("org.snapdragon.MX4Daemon1"),
        QStringLiteral("ActionRingPressed"),
        this,
        SLOT(toggleOverlay()));
}

// ---------------------------------------------------------------------------

void RadialWindow::showOverlay()
{
    if (!isVisible()) {
        // Center on the primary screen
        if (auto* screen = QApplication::primaryScreen()) {
            const QRect geom = screen->availableGeometry();
            move(geom.center() - rect().center());
        }
        show();
        raise();
        activateWindow();
    }
}

void RadialWindow::hideOverlay()
{
    if (isVisible()) hide();
}

void RadialWindow::toggleOverlay()
{
    if (isVisible()) hideOverlay(); else showOverlay();
}

// ---------------------------------------------------------------------------

void RadialWindow::keyPressEvent(QKeyEvent* event)
{
    if (event->key() == Qt::Key_Escape)
        hideOverlay();
    else
        QWidget::keyPressEvent(event);
}

void RadialWindow::focusOutEvent(QFocusEvent* event)
{
    hideOverlay();
    QWidget::focusOutEvent(event);
}
