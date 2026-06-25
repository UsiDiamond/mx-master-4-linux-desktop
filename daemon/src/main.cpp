#include <QCoreApplication>
#include <QDBusConnection>
#include <QTextStream>

#include "daemon.h"

int main(int argc, char** argv)
{
    QCoreApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("mx4d"));
    app.setApplicationVersion(QStringLiteral("0.1.0"));
    app.setOrganizationName(QStringLiteral("UsiDiamond"));
    app.setOrganizationDomain(QStringLiteral("snapdragon.systems"));

    // Register the well-known service name on the session bus
    if (!QDBusConnection::sessionBus().isConnected()) {
        QTextStream(stderr) << "mx4d: cannot connect to session D-Bus\n";
        return 1;
    }

    if (!QDBusConnection::sessionBus().registerService(
            QStringLiteral("org.snapdragon.MX4Daemon1"))) {
        QTextStream(stderr) << "mx4d: service name already registered "
                            << "(another instance running?)\n";
        return 1;
    }

    MX4Daemon daemon;
    if (!QDBusConnection::sessionBus().registerObject(
            QStringLiteral("/"), &daemon,
            QDBusConnection::ExportAllSlots |
            QDBusConnection::ExportAllSignals))
    {
        QTextStream(stderr) << "mx4d: failed to register D-Bus object\n";
        return 1;
    }

    QTextStream(stdout) << "mx4d: running on org.snapdragon.MX4Daemon1\n";
    return app.exec();
}
