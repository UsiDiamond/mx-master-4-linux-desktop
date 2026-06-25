#pragma once
#include <QDBusConnection>
#include <QDBusMessage>
#include <QObject>
#include <QString>

/// NotificationsSource — monitors org.freedesktop.Notifications on the session bus.
///
/// Connects to the Notify method call (via a D-Bus match rule on the session bus) so
/// that the daemon can detect when any desktop notification is shown and trigger an
/// ambient haptic waveform.
///
/// The freedesktop Notifications spec does not expose a "notification shown" signal;
/// instead we snoop on method calls to the well-known name using a QDBusConnection
/// match rule for:
///   interface = org.freedesktop.Notifications
///   member    = Notify
///
/// Additionally monitors NotificationClosed(id, reason) for "dismiss" haptics.
class NotificationsSource : public QObject {
    Q_OBJECT

public:
    explicit NotificationsSource(QObject* parent = nullptr);
    ~NotificationsSource() override;

Q_SIGNALS:
    /// Emitted when any application calls org.freedesktop.Notifications.Notify.
    /// @param appName   Application name string (arg0 of the Notify call)
    /// @param summary   Notification summary string (arg3 of the Notify call)
    void notificationArrived(const QString& appName, const QString& summary);

    /// Emitted when a notification is closed (id, reason).
    void notificationClosed(quint32 id, quint32 reason);

private Q_SLOTS:
    void onNotifyMessage(const QDBusMessage& message);
    void onClosedMessage(const QDBusMessage& message);

private:
    void connectToSessionBus();
};
