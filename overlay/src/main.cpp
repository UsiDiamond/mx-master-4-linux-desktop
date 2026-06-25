#include <QCommandLineParser>
#include <QDBusConnection>
#include <QGuiApplication>
#include <QIcon>
#include <QLoggingCategory>
#include <QPainter>
#include <QPixmap>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickImageProvider>
#include <QQuickView>
#include <QQuickWindow>
#include <QScreen>
#include <QTimer>

#include "DaemonHaptics.h"
#include "MenuConfig.h"
#include "OverlayService.h"
#include "PlatformWindow.h"
#include "RadialController.h"

Q_LOGGING_CATEGORY(lcMain, "mx4.main")

using namespace mx4;

namespace {

constexpr int kOverlaySize = 520; // square content size

// Serves freedesktop theme icons to QML as "image://theme/<icon-name>".
// Falls back to a transparent pixmap when the icon is absent, so QML never
// shows a broken-image box and never crashes.
class ThemeIconProvider : public QQuickImageProvider
{
public:
    ThemeIconProvider()
        : QQuickImageProvider(QQuickImageProvider::Pixmap) {}

    QPixmap requestPixmap(const QString &id, QSize *size,
                          const QSize &requestedSize) override
    {
        const int dim = requestedSize.width() > 0 ? requestedSize.width() : 48;
        QIcon icon = QIcon::fromTheme(id);
        QPixmap pm = icon.isNull() ? QPixmap() : icon.pixmap(QSize(dim, dim));
        if (pm.isNull()) {
            pm = QPixmap(dim, dim);
            pm.fill(Qt::transparent);
        }
        if (size) {
            *size = pm.size();
        }
        return pm;
    }
};

// Build (or rebuild) the QQuickView for a fresh menu show. Returns a raw
// pointer owned by the QObject tree (parented to app).
QQuickView *makeView(QGuiApplication &app,
                     RadialController *controller,
                     PlatformWindow *platform)
{
    // QQuickView's parent must be a QWindow; we manage its lifetime explicitly
    // via deleteLater() on hide, so it takes no parent here (no leak).
    Q_UNUSED(app);
    auto *view = new QQuickView();
    view->setResizeMode(QQuickView::SizeRootObjectToView);
    view->resize(kOverlaySize, kOverlaySize);

    // Engine takes ownership of the provider.
    view->engine()->addImageProvider(QStringLiteral("theme"),
                                     new ThemeIconProvider);

    view->rootContext()->setContextProperty(QStringLiteral("Radial"),
                                             controller);

    // Backend-appropriate frameless/translucent/top-most setup BEFORE loading
    // the QML so the surface role is set before first map.
    platform->configure(view, QSize(kOverlaySize, kOverlaySize));

    view->setSource(QUrl(QStringLiteral("qrc:/qml/RadialMenu.qml")));
    if (view->status() == QQuickView::Error) {
        const auto errs = view->errors();
        for (const auto &e : errs) {
            qCCritical(lcMain) << "QML error:" << e.toString();
        }
    }
    return view;
}

} // namespace

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("mx4-radial"));
    app.setOrganizationName(QStringLiteral("usidiamond"));
    app.setApplicationVersion(QStringLiteral("0.1.0"));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("MX Master 4 radial menu overlay"));
    parser.addHelpOption();
    parser.addVersionOption();
    QCommandLineOption demoOpt(
        QStringList{QStringLiteral("demo")},
        QStringLiteral("Show the menu immediately and quit on dismiss "
                       "(standalone, no daemon needed)."));
    QCommandLineOption menuOpt(
        QStringList{QStringLiteral("menu")},
        QStringLiteral("Menu id to show (default 'default')."),
        QStringLiteral("id"), QStringLiteral("default"));
    parser.addOption(demoOpt);
    parser.addOption(menuOpt);
    parser.process(app);

    const bool demo = parser.isSet(demoOpt);
    const QString cliMenuId = parser.value(menuOpt);

    // --- core objects (all parented to app -> no leaks) -------------------
    auto *haptics = new DaemonHaptics(&app);
    auto *controller = new RadialController(haptics, &app);
    auto *platform = new PlatformWindow(&app);

    // The currently-shown view (recreated per Show so the surface role is fresh
    // on Wayland). nullptr when hidden.
    QQuickView *view = nullptr;

    // Helper to hide & destroy the current view.
    auto hideView = [&view]() {
        if (view) {
            view->hide();
            view->deleteLater();
            view = nullptr;
        }
    };

    // Helper to (re)show the menu for a given menu id (selects the config
    // section; empty/"default" -> [radial]).
    auto showView = [&](const QString &menuId) {
        if (view) {
            hideView();
        }
        // Reload config each show so live edits land without a restart. The
        // menu id selects the [radial:<id>] section (falls back to [radial]).
        MenuConfig fresh(menuId.isEmpty() ? QStringLiteral("default") : menuId);
        controller->setMenu(fresh);
        view = makeView(app, controller, platform);
        view->show();
        platform->positionForShow(view, QSize(kOverlaySize, kOverlaySize));
        view->requestActivate();
    };

    // controller -> dismiss wiring (Escape / commit / outside click).
    QObject::connect(controller, &RadialController::dismissRequested,
                     &app, [&]() {
        hideView();
        if (demo) {
            QTimer::singleShot(120, &app, &QGuiApplication::quit);
        }
    });

    // --- D-Bus Overlay service (skipped in demo for standalone runnability) -
    OverlayService *service = nullptr;
    if (!demo) {
        service = new OverlayService(&app);

        QObject::connect(service, &OverlayService::showRequested,
                         &app, [&](const QString &menuId) {
                             // An empty menu id from the bus falls back to the
                             // CLI default (--menu), then to [radial].
                             showView(menuId.isEmpty() ? cliMenuId : menuId);
                         });
        QObject::connect(service, &OverlayService::hideRequested,
                         &app, [&]() { hideView(); });

        // Programmatic Commit/Activate: ensure the menu is loaded (show it if
        // hidden, so the controller holds the right segments), then drive the
        // SAME commit path a user release would. The commit emits dismissed,
        // which tears the view down — full show->commit->launch, no tap needed.
        // These are plain handlers (not signals), so QtDBus never tries to relay
        // them and there is no spurious "pointers not supported" warning.
        service->setCommitHandler([&](const QString &actionId) -> bool {
            if (!view) {
                showView(cliMenuId);
            }
            return controller->commitById(actionId);
        });
        service->setActivateHandler([&](int index) -> bool {
            if (!view) {
                showView(cliMenuId);
            }
            return controller->commitByIndex(index);
        });

        // Bridge the controller's choice out over the bus.
        QObject::connect(controller, &RadialController::actionChosen,
                         service, &OverlayService::ActionChosen);

        QDBusConnection bus = QDBusConnection::sessionBus();
        if (!bus.isConnected()) {
            qCWarning(lcMain) << "no session bus; running headless idle";
        } else {
            if (!bus.registerObject(
                    QString::fromLatin1(OverlayService::objectPath()),
                    service,
                    QDBusConnection::ExportScriptableContents)) {
                qCWarning(lcMain) << "failed to register D-Bus object"
                                  << OverlayService::objectPath();
            }
            if (!bus.registerService(
                    QString::fromLatin1(OverlayService::busName()))) {
                // We own a name distinct from the daemon's, so a failure here
                // means another overlay instance is already running. The object
                // is still exported on this connection; log & continue.
                qCWarning(lcMain) << "could not own bus name"
                                  << OverlayService::busName()
                                  << "(another overlay running?); object still"
                                  << "exported";
            } else {
                qCInfo(lcMain) << "registered" << OverlayService::busName()
                               << "waiting for Show()";
            }
        }
    }

    // --- run --------------------------------------------------------------
    if (demo) {
        // Show immediately. A safety timer auto-dismisses so the process never
        // hangs forever in a headless CI even if no input arrives.
        showView(cliMenuId);
        QTimer::singleShot(15000, &app, [&]() {
            qCInfo(lcMain) << "demo safety timeout; dismissing";
            controller->cancel();
        });
    }

    return app.exec();
}
