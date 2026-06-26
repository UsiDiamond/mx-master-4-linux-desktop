#include "PlatformWindow.h"

#include <QCursor>
#include <QGuiApplication>
#include <QLoggingCategory>
#include <QQuickView>
#include <QQuickWindow>
#include <QScreen>

#ifdef MX4_HAVE_LAYERSHELL
#include <LayerShellQt/Window>
#endif

Q_LOGGING_CATEGORY(lcPlatform, "mx4.platform")

namespace mx4 {

PlatformWindow::PlatformWindow(QObject *parent)
    : QObject(parent)
{
    const QString platform = QGuiApplication::platformName();
    if (platform.startsWith(QLatin1String("wayland"))) {
#ifdef MX4_HAVE_LAYERSHELL
        m_backend = Backend::WaylandLayerShell;
#else
        qCWarning(lcPlatform)
            << "Wayland session but built without LayerShellQt; using fallback";
        m_backend = Backend::Fallback;
#endif
    } else if (platform == QLatin1String("xcb")) {
        m_backend = Backend::X11Cursor;
    } else {
        m_backend = Backend::Fallback;
    }
    qCInfo(lcPlatform) << "platform=" << platform
                       << "backend=" << static_cast<int>(m_backend);
}

void PlatformWindow::configure(QQuickView *view, const QSize &desiredSize)
{
    if (!view) {
        return;
    }
    // Common: frameless + translucent so the QML ring floats on nothing.
    view->setColor(Qt::transparent);
    view->setFlag(Qt::FramelessWindowHint, true);

    switch (m_backend) {
    case Backend::WaylandLayerShell:
        configureWayland(view, desiredSize);
        break;
    case Backend::X11Cursor:
        configureX11(view);
        break;
    case Backend::Fallback:
        configureFallback(view);
        break;
    }
}

void PlatformWindow::configureWayland(QQuickWindow *window, const QSize &desiredSize)
{
#ifdef MX4_HAVE_LAYERSHELL
    // Window::get() creates (and parents to the QWindow) the layer-shell
    // wrapper; ownership stays with the QWindow, so no manual delete.
    LayerShellQt::Window *ls = LayerShellQt::Window::get(window);
    if (!ls) {
        qCWarning(lcPlatform) << "LayerShellQt::Window::get returned null; "
                                 "falling back to plain window";
        configureFallback(window);
        return;
    }
    ls->setLayer(LayerShellQt::Window::LayerOverlay);
    // No anchors -> compositor centers the surface (Wayland can't place at the
    // cursor; this is the expected behaviour, see header).
    ls->setAnchors(LayerShellQt::Window::Anchors());
    ls->setExclusiveZone(0);
    // OnDemand: the surface CAN receive keyboard focus (needed for Escape /
    // arrows). KeyboardInteractivityNone would leave us deaf to keys.
    ls->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityOnDemand);
    ls->setActivateOnShow(true);
    ls->setScope(QStringLiteral("mx4-radial"));
    ls->setCloseOnDismissed(false);
    ls->setDesiredSize(desiredSize);
    qCInfo(lcPlatform) << "configured Wayland layer-shell overlay (centered)";
#else
    Q_UNUSED(desiredSize);
    configureFallback(window);
#endif
}

void PlatformWindow::configureX11(QQuickWindow *window)
{
    // Qt::Tool keeps it off the taskbar; top-most; bypass WM decorations.
    window->setFlag(Qt::Tool, true);
    window->setFlag(Qt::WindowStaysOnTopHint, true);
    window->setFlag(Qt::X11BypassWindowManagerHint, false);
    qCInfo(lcPlatform) << "configured X11 cursor-anchored overlay";
}

void PlatformWindow::configureFallback(QQuickWindow *window)
{
    window->setFlag(Qt::Tool, true);
    window->setFlag(Qt::WindowStaysOnTopHint, true);
    qCInfo(lcPlatform) << "configured fallback frameless overlay";
}

void PlatformWindow::positionForShow(QQuickWindow *window, const QSize &desiredSize)
{
    if (!window) {
        return;
    }
    const QPoint cursor = QCursor::pos();
    QScreen *screen = QGuiApplication::screenAt(cursor);
    if (!screen) {
        screen = QGuiApplication::primaryScreen();
    }
    qCInfo(lcPlatform) << "show: cursor" << cursor << "-> screen"
                       << (screen ? screen->name() : QStringLiteral("?"))
                       << (screen ? screen->geometry() : QRect());

    if (m_backend == Backend::X11Cursor || m_backend == Backend::Fallback) {
        const QRect bounds = screen->geometry();
        // Bind the window to the cursor's screen so a multi-monitor map lands on
        // the right output (must be set before show()); then center on the
        // pointer, clamped fully within that screen.
        window->setScreen(screen);
        QPoint topLeft(cursor.x() - desiredSize.width() / 2,
                       cursor.y() - desiredSize.height() / 2);
        topLeft.setX(qBound(bounds.left(), topLeft.x(),
                            bounds.right() - desiredSize.width()));
        topLeft.setY(qBound(bounds.top(), topLeft.y(),
                            bounds.bottom() - desiredSize.height()));
        window->setPosition(topLeft);
    } else {
        // Wayland layer-shell can't place at an absolute x,y, but binding the
        // surface to the cursor's screen makes the compositor center it on the
        // RIGHT output. Best-effort: if QCursor::pos() is unreliable here it
        // falls back to the primary screen (same as before).
        window->setScreen(screen);
    }
}

} // namespace mx4
