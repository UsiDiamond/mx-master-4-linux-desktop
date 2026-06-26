#include "DaemonBridge.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDBusServiceWatcher>
#include <QHash>
#include <QLoggingCategory>

Q_LOGGING_CATEGORY(lcBridge, "mx4.bridge")

namespace mx4 {

namespace {
constexpr char kBusName[]    = "dev.usidiamond.mx4";
constexpr char kObjectPath[] = "/dev/usidiamond/mx4";
constexpr char kInterface[]  = "dev.usidiamond.mx4.Daemon";

// Waveform NAME -> firmware index. Mirrors daemon/mx4d/haptics.py WAVEFORMS, so
// supportedWaveform() can test bit (1 << index) of the capability mask exactly
// the way HapticEngine.supports() does.
const QHash<QString, int> kWaveformIndex = {
    {QStringLiteral("SHARP_STATE_CHANGE"), 0x00},
    {QStringLiteral("DAMP_STATE_CHANGE"), 0x01},
    {QStringLiteral("SHARP_COLLISION"), 0x02},
    {QStringLiteral("DAMP_COLLISION"), 0x03},
    {QStringLiteral("SUBTLE_COLLISION"), 0x04},
    {QStringLiteral("HAPPY_ALERT"), 0x05},
    {QStringLiteral("ANGRY_ALERT"), 0x06},
    {QStringLiteral("COMPLETED"), 0x07},
    {QStringLiteral("SQUARE"), 0x08},
    {QStringLiteral("WAVE"), 0x09},
    {QStringLiteral("FIREWORK"), 0x0A},
    {QStringLiteral("MAD"), 0x0B},
    {QStringLiteral("KNOCK"), 0x0C},
    {QStringLiteral("JINGLE"), 0x0D},
    {QStringLiteral("RINGING"), 0x0E},
    {QStringLiteral("WHISPER_COLLISION"), 0x1B},
};
} // namespace

DaemonBridge::DaemonBridge(QObject *parent)
    : QObject(parent)
{
    QDBusConnection bus = QDBusConnection::sessionBus();

    if (auto *conn = bus.interface()) {
        m_present = conn->isServiceRegistered(QLatin1String(kBusName)).value();
    }

    m_watcher = new QDBusServiceWatcher(
        QLatin1String(kBusName), bus,
        QDBusServiceWatcher::WatchForRegistration
            | QDBusServiceWatcher::WatchForUnregistration,
        this);
    connect(m_watcher, &QDBusServiceWatcher::serviceRegistered,
            this, &DaemonBridge::onDaemonRegistered);
    connect(m_watcher, &QDBusServiceWatcher::serviceUnregistered,
            this, &DaemonBridge::onDaemonUnregistered);

    if (m_present) {
        refreshCapabilities();
    }
    qCInfo(lcBridge) << "daemon initially"
                     << (m_present ? "present" : "absent");
}

int DaemonBridge::waveformIndex(const QString &name)
{
    const QString key = name.trimmed().toUpper();
    return kWaveformIndex.value(key, -1);
}

QDBusInterface *DaemonBridge::iface() const
{
    if (!m_iface) {
        m_iface = new QDBusInterface(QLatin1String(kBusName),
                                     QLatin1String(kObjectPath),
                                     QLatin1String(kInterface),
                                     QDBusConnection::sessionBus(),
                                     const_cast<DaemonBridge *>(this));
    }
    return m_iface;
}

void DaemonBridge::onDaemonRegistered()
{
    m_present = true;
    if (m_iface) {
        m_iface->deleteLater();
        m_iface = nullptr;
    }
    qCInfo(lcBridge) << "daemon appeared";
    emit availabilityChanged();
    refreshCapabilities();
}

void DaemonBridge::onDaemonUnregistered()
{
    m_present = false;
    m_haveCapabilities = false;
    m_capabilities = 0;
    if (m_iface) {
        m_iface->deleteLater();
        m_iface = nullptr;
    }
    qCInfo(lcBridge) << "daemon left";
    emit availabilityChanged();
    emit capabilitiesChanged();
}

void DaemonBridge::refreshCapabilities()
{
    if (!m_present) {
        return;
    }
    QDBusInterface *i = iface();
    if (!i->isValid()) {
        return;
    }
    // GetCapabilities()->u returns the firmware supported-waveform bitmask.
    QDBusReply<uint> reply = i->call(QStringLiteral("GetCapabilities"));
    if (reply.isValid()) {
        m_capabilities = reply.value();
        m_haveCapabilities = true;
        qCInfo(lcBridge) << "capability mask"
                         << QString::number(m_capabilities, 16);
    } else {
        // Older daemon without GetCapabilities: leave mask unknown so the UI
        // shows all waveforms (rather than greying everything out).
        m_haveCapabilities = false;
        m_capabilities = 0;
        qCDebug(lcBridge) << "GetCapabilities unavailable:"
                          << reply.error().message();
    }
    emit capabilitiesChanged();
}

void DaemonBridge::playHaptic(const QString &waveform)
{
    if (!m_present) {
        qCDebug(lcBridge) << "daemon absent; would PlayHaptic" << waveform;
        return;
    }
    QDBusInterface *i = iface();
    if (!i->isValid()) {
        qCDebug(lcBridge) << "iface invalid:" << i->lastError().message();
        return;
    }
    // Fire-and-forget: never block the UI on the motor.
    i->asyncCall(QStringLiteral("PlayHaptic"), waveform);
    qCDebug(lcBridge) << "PlayHaptic" << waveform;
}

void DaemonBridge::setLevel(int level)
{
    if (!m_present) {
        return;
    }
    QDBusInterface *i = iface();
    if (!i->isValid()) {
        return;
    }
    i->asyncCall(QStringLiteral("SetLevel"), level);
    qCDebug(lcBridge) << "SetLevel" << level;
}

bool DaemonBridge::supportedWaveform(const QString &name) const
{
    // Unknown mask (daemon absent or old) => don't grey anything out.
    if (!m_present || !m_haveCapabilities) {
        return true;
    }
    const int idx = waveformIndex(name);
    if (idx < 0) {
        return true; // unknown name; don't claim it's unsupported
    }
    return (m_capabilities & (1u << idx)) != 0;
}

} // namespace mx4
