#include <QGuiApplication>
#include <QIcon>
#include <QLoggingCategory>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>

#include "ConfigModel.h"
#include "DaemonBridge.h"

Q_LOGGING_CATEGORY(lcMain, "mx4.config.main")

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("mx4-config"));
    app.setOrganizationName(QStringLiteral("usidiamond"));
    app.setApplicationDisplayName(
        QStringLiteral("MX Master 4 Settings"));
    app.setApplicationVersion(QStringLiteral("0.1.0"));
    app.setWindowIcon(QIcon::fromTheme(QStringLiteral("input-mouse")));

    // QtQuick Controls 2 style. Prefer the system style on Plasma; fall back to
    // the always-present Fusion style on LXQt / minimal setups (NO KF6 needed).
    if (QQuickStyle::name().isEmpty()) {
        if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE")) {
            // org.kde.desktop blends into Plasma; if its plugin is absent Qt
            // silently uses the default, and Fusion is our guaranteed fallback.
            QQuickStyle::setFallbackStyle(QStringLiteral("Fusion"));
        }
    }

    // Backends exposed to QML. Parented to the app -> no leaks.
    auto *config = new mx4::ConfigModel(&app);
    auto *daemon = new mx4::DaemonBridge(&app);

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("Config"), config);
    engine.rootContext()->setContextProperty(QStringLiteral("Daemon"), daemon);

    QObject::connect(
        &engine, &QQmlApplicationEngine::objectCreationFailed, &app,
        []() {
            qCCritical(lcMain) << "QML failed to load";
            QCoreApplication::exit(1);
        },
        Qt::QueuedConnection);

    engine.load(QUrl(QStringLiteral("qrc:/qml/Main.qml")));
    if (engine.rootObjects().isEmpty()) {
        qCCritical(lcMain) << "no root QML object; aborting";
        return 1;
    }

    return app.exec();
}
