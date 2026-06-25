#ifndef MX4_PLATFORMWINDOW_H
#define MX4_PLATFORMWINDOW_H

#include <QObject>
#include <QSize>

class QQuickWindow;
class QQuickView;

namespace mx4 {

/**
 * Configures a QQuickView/QQuickWindow as a frameless, translucent,
 * stay-on-top overlay across the two backends:
 *
 *  - Wayland (Plasma 6): wlr-layer-shell via LayerShellQt. Layer = Overlay,
 *    anchors = none (so the compositor CENTERS the surface — Wayland clients
 *    cannot read the global cursor nor place a surface at absolute x,y, so
 *    center-screen is the correct, expected behaviour), exclusive zone = 0,
 *    keyboard interactivity = OnDemand (layer surfaces get NO keyboard by
 *    default; we need Escape/arrows). KDE treats OnDemand layer surfaces as a
 *    toolbar-equivalent, which is the type that *can* take keyboard focus
 *    (a "dock" type cannot).
 *
 *  - X11 (LXQt / Plasma-X11): a plain frameless Qt::Tool window placed AT the
 *    cursor (X11 lets us query QCursor::pos()). Nicer UX, for free.
 *
 * Never throws / never crashes if LayerShellQt is missing or the platform is
 * neither: it degrades to a plain frameless top-most window.
 */
class PlatformWindow : public QObject
{
    Q_OBJECT
public:
    enum class Backend { WaylandLayerShell, X11Cursor, Fallback };

    explicit PlatformWindow(QObject *parent = nullptr);

    // Apply backend-appropriate flags/surface role to the view BEFORE show().
    // desiredSize is the overlay's content size.
    void configure(QQuickView *view, const QSize &desiredSize);

    // Position at the cursor on X11; no-op on Wayland (compositor centers).
    void positionForShow(QQuickWindow *window, const QSize &desiredSize);

    Backend backend() const { return m_backend; }

private:
    void configureWayland(QQuickWindow *window, const QSize &desiredSize);
    void configureX11(QQuickWindow *window);
    void configureFallback(QQuickWindow *window);

    Backend m_backend = Backend::Fallback;
};

} // namespace mx4

#endif // MX4_PLATFORMWINDOW_H
