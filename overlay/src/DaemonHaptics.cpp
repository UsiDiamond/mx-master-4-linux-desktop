#include "DaemonHaptics.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDBusServiceWatcher>
#include <QLoggingCategory>

Q_LOGGING_CATEGORY(lcHaptics, "mx4.haptics")

namespace mx4 {

namespace {
constexpr char kBusName[]   = "dev.usidiamond.mx4";
constexpr char kObjectPath[] = "/dev/usidiamond/mx4";
constexpr char kInterface[] = "dev.usidiamond.mx4.Daemon";
} // namespace

DaemonHaptics::DaemonHaptics(QObject *parent)
    : QObject(parent)
{
    m_debounce.start();

    QDBusConnection bus = QDBusConnection::sessionBus();

    // Seed the cached presence with ONE synchronous check at startup (off the
    // input hot path), then keep it fresh via the watcher below.
    if (auto *conn = bus.interface()) {
        m_daemonPresent =
            conn->isServiceRegistered(QLatin1String(kBusName)).value();
    }

    // Watch for the daemon appearing/disappearing so the hover/commit paths
    // never pay a synchronous NameHasOwner round-trip.
    m_watcher = new QDBusServiceWatcher(
        QLatin1String(kBusName), bus,
        QDBusServiceWatcher::WatchForRegistration
            | QDBusServiceWatcher::WatchForUnregistration,
        this);
    connect(m_watcher, &QDBusServiceWatcher::serviceRegistered,
            this, &DaemonHaptics::onDaemonRegistered);
    connect(m_watcher, &QDBusServiceWatcher::serviceUnregistered,
            this, &DaemonHaptics::onDaemonUnregistered);

    qCDebug(lcHaptics) << "daemon initially"
                       << (m_daemonPresent ? "present" : "absent");
}

void DaemonHaptics::onDaemonRegistered()
{
    m_daemonPresent = true;
    // Drop any stale interface so a freshly-(re)started daemon is re-resolved.
    if (m_iface) {
        m_iface->deleteLater();
        m_iface = nullptr;
    }
    qCDebug(lcHaptics) << "daemon appeared on the bus";
}

void DaemonHaptics::onDaemonUnregistered()
{
    m_daemonPresent = false;
    if (m_iface) {
        m_iface->deleteLater();
        m_iface = nullptr;
    }
    qCDebug(lcHaptics) << "daemon left the bus";
}

QDBusInterface *DaemonHaptics::iface() const
{
    if (!m_iface) {
        // Parent to a const-cast of this: lifetime tied to the DaemonHaptics
        // object, so no manual delete and no leak.
        m_iface = new QDBusInterface(QLatin1String(kBusName),
                                     QLatin1String(kObjectPath),
                                     QLatin1String(kInterface),
                                     QDBusConnection::sessionBus(),
                                     const_cast<DaemonHaptics *>(this));
    }
    return m_iface;
}

void DaemonHaptics::play(const QString &waveform, bool debounced)
{
    if (debounced && m_debounce.elapsed() < m_debounceMs) {
        return; // swallow machine-gun hover changes
    }
    m_debounce.restart();

    if (!daemonAvailable()) {
        qCDebug(lcHaptics) << "daemon absent; would PlayHaptic" << waveform;
        return;
    }

    // Fire-and-forget async call: the overlay must never block on the motor.
    QDBusInterface *i = iface();
    if (!i->isValid()) {
        qCDebug(lcHaptics) << "haptics iface invalid:"
                           << i->lastError().message();
        return;
    }
    i->asyncCall(QStringLiteral("PlayHaptic"), waveform);
    qCDebug(lcHaptics) << "PlayHaptic" << waveform;
}

void DaemonHaptics::tick()
{
    play(QStringLiteral("SUBTLE_COLLISION"), /*debounced=*/true);
}

void DaemonHaptics::confirm()
{
    play(QStringLiteral("COMPLETED"), /*debounced=*/false);
}

void DaemonHaptics::cancelBuzz()
{
    // DAMP_STATE_CHANGE (0x01) is a real firmware waveform (see docs/RESEARCH.md
    // table); it reads as a soft "undo/dismiss". "DENIED" is NOT in the table
    // and would silently no-op on real hardware.
    play(QStringLiteral("DAMP_STATE_CHANGE"), /*debounced=*/false);
}

} // namespace mx4
