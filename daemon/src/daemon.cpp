#include "daemon.h"
#include "notifications_source.h"

#include <mx4hidpp/hidpp_device.h>
#include <mx4hidpp/feature_index.h>
#include <mx4hidpp/haptics.h>
#include <mx4hidpp/trigger.h>

#include <QCoreApplication>
#include <QThread>

// Default hidraw path (overridable via MX4_HIDRAW env var)
static constexpr const char* DEFAULT_HIDRAW = "/dev/hidraw11";
static constexpr uint8_t DEVICE_INDEX = 2;

// ---------------------------------------------------------------------------

MX4Daemon::MX4Daemon(QObject* parent)
    : QObject(parent)
{
    initDevice();

    m_notifSource = std::make_unique<NotificationsSource>(this);
    connect(m_notifSource.get(), &NotificationsSource::notificationArrived,
            this, [this](const QString& app, const QString& summary) {
                emit notificationReceived(app, summary);
                // Ambient haptic: HAPPY_ALERT for any notification (configurable in future)
                if (m_haptics && m_device)
                    m_haptics->playWaveform(*m_device,
                                            static_cast<uint8_t>(HapticsFeature::HappyAlert),
                                            60);
            });

    // TODO(P1): startTriggerLoop() — start polling thread for Actions Ring CID
}

MX4Daemon::~MX4Daemon()
{
    if (m_device) m_device->close();
}

// ---------------------------------------------------------------------------

void MX4Daemon::initDevice()
{
    const QByteArray hidrawEnv = qgetenv("MX4_HIDRAW");
    const std::string hidrawPath = hidrawEnv.isEmpty()
        ? DEFAULT_HIDRAW
        : hidrawEnv.toStdString();

    m_device = std::make_unique<HidppDevice>(hidrawPath, DEVICE_INDEX);
    if (!m_device->open()) {
        // Non-fatal at startup — device may not be present (Bluetooth off, etc.)
        // The daemon remains alive and will be woken when the device reconnects.
        m_device.reset();
        return;
    }

    // Resolve haptics feature index at runtime
    auto hapticsIdx = FeatureIndex::resolve(*m_device, HapticsFeature::FEATURE_NUMBER);
    if (hapticsIdx)
        m_haptics = std::make_unique<HapticsFeature>(*hapticsIdx);

    // Resolve trigger feature index at runtime
    auto triggerIdx = FeatureIndex::resolve(*m_device, TriggerFeature::FEATURE_NUMBER);
    if (triggerIdx)
        m_trigger = std::make_unique<TriggerFeature>(*triggerIdx);
}

// ---------------------------------------------------------------------------

void MX4Daemon::startTriggerLoop()
{
    if (!m_trigger || !m_device) return;

    // Divert the Actions Ring CID so presses come as HID++ notifications
    m_trigger->divertCid(*m_device, TriggerFeature::CID_ACTIONS_RING, true);

    // Run the blocking read loop on a dedicated thread
    auto* thread = QThread::create([this]() {
        while (m_device && m_device->isOpen()) {
            const int16_t cid = m_trigger->readDivertedCid(*m_device, 500);
            if (cid > 0)
                emit ActionRingPressed(static_cast<quint16>(cid));
        }
    });
    thread->setParent(this);
    thread->start();
}

// ---------------------------------------------------------------------------

void MX4Daemon::PlayHaptic(quint8 waveform, quint8 intensity)
{
    if (m_haptics && m_device)
        m_haptics->playWaveform(*m_device, waveform, intensity);
}

void MX4Daemon::SetHapticLevel(quint8 level)
{
    if (m_haptics && m_device)
        m_haptics->setLevel(*m_device, level);
}
