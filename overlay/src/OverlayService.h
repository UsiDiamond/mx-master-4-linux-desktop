#ifndef MX4_OVERLAYSERVICE_H
#define MX4_OVERLAYSERVICE_H

#include <QObject>
#include <QString>

namespace mx4 {

/**
 * D-Bus adaptor surface for the overlay process.
 *
 *   bus name : dev.usidiamond.mx4.Overlay   (distinct from the daemon's
 *              dev.usidiamond.mx4, which the overlay only calls for haptics)
 *   object   : /dev/usidiamond/mx4/Overlay
 *   interface: dev.usidiamond.mx4.Overlay
 *
 * Exposes Show(s menuId) / Hide() and emits ActionChosen(s actionId). The
 * daemon's RadialController calls Show to raise the menu; the overlay emits
 * ActionChosen when the user commits.
 *
 * This class is exported with auto-generated D-Bus introspection by tagging the
 * methods/signals as scriptable slots/signals and registering it on the bus
 * with ExportScriptableContents.
 */
class OverlayService : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "dev.usidiamond.mx4.Overlay")
public:
    explicit OverlayService(QObject *parent = nullptr);

    static const char *busName();
    static const char *objectPath();
    static const char *interfaceName();

public slots: // exported as D-Bus methods
    Q_SCRIPTABLE void Show(const QString &menuId);
    Q_SCRIPTABLE void Hide();

signals: // exported as D-Bus signals
    Q_SCRIPTABLE void ActionChosen(const QString &actionId);

    // Internal Qt signals (not over the bus) the app wires to the window.
    void showRequested(const QString &menuId);
    void hideRequested();
};

} // namespace mx4

#endif // MX4_OVERLAYSERVICE_H
