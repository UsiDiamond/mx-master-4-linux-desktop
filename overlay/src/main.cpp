#include <QApplication>
#include <QTextStream>

#include "radial_window.h"

int main(int argc, char** argv)
{
    // Qt::AA_UseHighDpiPixmaps is default-on in Qt6
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("mx4-radial"));
    app.setApplicationVersion(QStringLiteral("0.1.0"));
    app.setOrganizationName(QStringLiteral("UsiDiamond"));
    app.setOrganizationDomain(QStringLiteral("snapdragon.systems"));

    RadialWindow window;
    // The window starts hidden; it becomes visible when ActionRingPressed
    // arrives over D-Bus (connected inside RadialWindow::connectDaemonSignal).
    // Show it immediately in debug mode so you can verify the layout.
    const bool debugShow = qgetenv("MX4_RADIAL_DEBUG") == "1";
    if (debugShow) window.showOverlay();

    QTextStream(stdout) << "mx4-radial: listening for org.snapdragon.MX4Daemon1.ActionRingPressed\n";
    return app.exec();
}
