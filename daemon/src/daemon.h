#pragma once
#include <QObject>
#include <QString>
#include <cstdint>
#include <memory>

class HidppDevice;
class HapticsFeature;
class TriggerFeature;
class NotificationsSource;

/// MX4Daemon — the core Qt D-Bus service object.
///
/// Registered on the session bus as "org.snapdragon.MX4Daemon1" at object path "/".
///
/// Responsibilities:
///   - Open and own the HidppDevice
///   - Expose PlayHaptic / SetHapticLevel as D-Bus slots
///   - Emit ActionRingPressed signal when the Actions Ring button is diverted
///   - Own a NotificationsSource that triggers ambient haptics on notifications
class MX4Daemon : public QObject {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.snapdragon.MX4Daemon1")

public:
    explicit MX4Daemon(QObject* parent = nullptr);
    ~MX4Daemon() override;

public Q_SLOTS:
    /// D-Bus method: play a haptic waveform with the given intensity.
    /// @param waveform  Waveform index (see HapticsFeature::Waveform)
    /// @param intensity Motor level override 0-100 (0 = use device stored level)
    void PlayHaptic(quint8 waveform, quint8 intensity);

    /// D-Bus method: set the persistent motor intensity level.
    void SetHapticLevel(quint8 level);

Q_SIGNALS:
    /// Emitted when the Actions Ring button press is captured via 0x1B04 divert.
    void ActionRingPressed(quint16 cid);

    /// Internal: emitted when a desktop notification arrives (for ambient haptics).
    void notificationReceived(const QString& appName, const QString& summary);

private:
    void initDevice();
    void startTriggerLoop();

    std::unique_ptr<HidppDevice>       m_device;
    std::unique_ptr<HapticsFeature>    m_haptics;
    std::unique_ptr<TriggerFeature>    m_trigger;
    std::unique_ptr<NotificationsSource> m_notifSource;
};
