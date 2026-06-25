#ifndef MX4_OVERLAYSERVICE_H
#define MX4_OVERLAYSERVICE_H

#include <QObject>
#include <QString>

#include <functional>

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

    // Raise the MPRIS media-controls panel (the press-and-hold target) instead
    // of a radial ring.
    Q_SCRIPTABLE void ShowMedia();

    // Programmatic commit of a segment as if the user selected it, driving the
    // same commit()/launch path. Returns whether a matching item was committed.
    // Commit("")/Commit("center") commits the center hub action. These make the
    // full show->commit->launch chain automatable on Wayland with no physical
    // tap (the overlay is shown first if it is not already visible).
    Q_SCRIPTABLE bool Commit(const QString &actionId);
    Q_SCRIPTABLE bool Activate(int index); // -1 = center, 0..n-1 = segment

public:
    // Handlers the app installs to service a programmatic Commit/Activate. They
    // run synchronously inside the D-Bus call and return success, which becomes
    // the method's reply. Plain callbacks (NOT signals) so QtDBus never tries to
    // relay a pointer-bearing signal over the bus.
    using CommitHandler = std::function<bool(const QString &actionId)>;
    using ActivateHandler = std::function<bool(int index)>;
    void setCommitHandler(CommitHandler handler) { m_commitHandler = std::move(handler); }
    void setActivateHandler(ActivateHandler handler) { m_activateHandler = std::move(handler); }

    // Emit the Dismissed D-Bus signal (the overlay just closed for any reason:
    // a committed action, a cancel, or an external Hide). The daemon listens so
    // it can track visibility for press-again-to-dismiss.
    void notifyDismissed() { emit Dismissed(); }

signals: // exported as D-Bus signals
    Q_SCRIPTABLE void ActionChosen(const QString &actionId);
    // Fired whenever the overlay transitions to hidden (commit / cancel / Hide).
    Q_SCRIPTABLE void Dismissed();

    // Internal Qt signals (not over the bus) the app wires to the window.
    void showRequested(const QString &menuId);
    void showMediaRequested();
    void hideRequested();

private:
    CommitHandler m_commitHandler;
    ActivateHandler m_activateHandler;
};

} // namespace mx4

#endif // MX4_OVERLAYSERVICE_H
