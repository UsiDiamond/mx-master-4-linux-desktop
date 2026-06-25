#ifndef MX4_DAEMONHAPTICS_H
#define MX4_DAEMONHAPTICS_H

#include <QElapsedTimer>
#include <QObject>
#include <QString>

class QDBusInterface;
class QDBusServiceWatcher;

namespace mx4 {

/**
 * Thin QtDBus client for the haptic motor, owned by the daemon.
 *
 *   bus name : dev.usidiamond.mx4
 *   object   : /dev/usidiamond/mx4
 *   interface: dev.usidiamond.mx4.Daemon
 *   method   : PlayHaptic(s waveform)
 *
 * If the daemon is absent (demo mode), every call is a graceful no-op logged at
 * debug level. Hover ticks are debounced so rapid segment changes do not
 * machine-gun the motor.
 */
class DaemonHaptics : public QObject
{
    Q_OBJECT
public:
    explicit DaemonHaptics(QObject *parent = nullptr);

    // Is the daemon currently on the bus? Backed by a QDBusServiceWatcher so
    // the hot path (hover ticks / commit) reads a cached bool instead of a
    // synchronous bus round-trip.
    bool daemonAvailable() const { return m_daemonPresent; }

public slots:
    // Light tick as the highlighted segment changes (debounced).
    void tick();
    // Stronger confirmation on commit (not debounced).
    void confirm();
    // Cancel feedback on dismiss (not debounced).
    void cancelBuzz();
    // Arbitrary waveform passthrough.
    void play(const QString &waveform, bool debounced);

private slots:
    // QDBusServiceWatcher callbacks: keep the cached presence + iface fresh so a
    // daemon that appears/restarts mid-session is picked up cleanly.
    void onDaemonRegistered();
    void onDaemonUnregistered();

private:
    QDBusInterface *iface() const; // lazily created, parented to this

    QDBusServiceWatcher *m_watcher = nullptr;
    bool m_daemonPresent = false;
    mutable QDBusInterface *m_iface = nullptr;
    QElapsedTimer m_debounce;
    int m_debounceMs = 40; // floor between hover ticks
};

} // namespace mx4

#endif // MX4_DAEMONHAPTICS_H
