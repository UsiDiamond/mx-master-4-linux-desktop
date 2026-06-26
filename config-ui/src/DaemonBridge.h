#ifndef MX4_DAEMONBRIDGE_H
#define MX4_DAEMONBRIDGE_H

#include <QObject>
#include <QString>
#include <QStringList>

class QDBusInterface;
class QDBusServiceWatcher;

namespace mx4 {

/**
 * DaemonBridge — the config GUI's QtDBus client to the running daemon.
 *
 *   bus name : dev.usidiamond.mx4
 *   object   : /dev/usidiamond/mx4
 *   interface: dev.usidiamond.mx4.Daemon
 *
 * Used for two things:
 *   1. LIVE PREVIEW — playHaptic(name) calls Daemon.PlayHaptic(s) so the user
 *      feels a waveform from the GUI. Graceful no-op when the daemon is absent.
 *   2. CAPABILITY MASK — when the daemon is running, GetCapabilities()->u returns
 *      the firmware's supported-waveform bitmask; supportedWaveform(name) lets
 *      the QML mark which waveforms the hardware actually plays. When the daemon
 *      is absent the mask is 0 and the UI shows all waveforms with a note.
 *
 * Presence is tracked via QDBusServiceWatcher so the UI reflects the daemon
 * appearing/leaving without a synchronous probe on every interaction.
 */
class DaemonBridge : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool available READ available NOTIFY availabilityChanged)
    Q_PROPERTY(uint capabilities READ capabilities NOTIFY capabilitiesChanged)
    Q_PROPERTY(bool capabilitiesKnown READ capabilitiesKnown NOTIFY capabilitiesChanged)

public:
    explicit DaemonBridge(QObject *parent = nullptr);

    bool available() const { return m_present; }
    uint capabilities() const { return m_capabilities; }
    // True only when we have actually read a mask from a running daemon.
    bool capabilitiesKnown() const { return m_present && m_haveCapabilities; }

public slots:
    // Fire-and-forget live preview. Returns immediately; no-op if daemon absent.
    void playHaptic(const QString &waveform);

    // Push the global haptic level to the device live (Daemon.SetLevel).
    void setLevel(int level);

    // Is a waveform NAME supported by the firmware mask? When the mask is
    // unknown (daemon absent) returns true so nothing is greyed out wrongly.
    bool supportedWaveform(const QString &name) const;

    // Re-query the capability mask (e.g. after the daemon (re)appears).
    void refreshCapabilities();

signals:
    void availabilityChanged();
    void capabilitiesChanged();

private slots:
    void onDaemonRegistered();
    void onDaemonUnregistered();

private:
    QDBusInterface *iface() const;
    static int waveformIndex(const QString &name);

    QDBusServiceWatcher *m_watcher = nullptr;
    mutable QDBusInterface *m_iface = nullptr;
    bool m_present = false;
    bool m_haveCapabilities = false;
    uint m_capabilities = 0;
};

} // namespace mx4

#endif // MX4_DAEMONBRIDGE_H
