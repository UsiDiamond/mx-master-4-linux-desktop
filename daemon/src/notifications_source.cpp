#include "notifications_source.h"

#include <QDBusConnection>
#include <QDBusMessage>

// D-Bus match rules for snooping on org.freedesktop.Notifications
static constexpr const char* NOTIF_SERVICE   = "org.freedesktop.Notifications";
static constexpr const char* NOTIF_INTERFACE = "org.freedesktop.Notifications";
static constexpr const char* NOTIF_PATH      = "/org/freedesktop/Notifications";
static constexpr const char* NOTIFY_METHOD   = "Notify";
static constexpr const char* CLOSED_SIGNAL   = "NotificationClosed";

// ---------------------------------------------------------------------------

NotificationsSource::NotificationsSource(QObject* parent)
    : QObject(parent)
{
    connectToSessionBus();
}

NotificationsSource::~NotificationsSource()
{
    auto& bus = QDBusConnection::sessionBus();
    bus.disconnect(NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, NOTIFY_METHOD,
                   this, SLOT(onNotifyMessage(QDBusMessage)));
    bus.disconnect(NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, CLOSED_SIGNAL,
                   this, SLOT(onClosedMessage(QDBusMessage)));
}

// ---------------------------------------------------------------------------

void NotificationsSource::connectToSessionBus()
{
    auto& bus = QDBusConnection::sessionBus();

    // Snooping Notify method calls is not directly supported by QDBusConnection's
    // connect() (which is signal-oriented).  We register as a message filter on
    // the QDBusConnection raw message level via addMatch, then connect to the
    // session bus signal for NotificationClosed which IS a proper signal.

    // Monitor the NotificationClosed SIGNAL (standard DBus signal — works directly)
    bus.connect(NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, CLOSED_SIGNAL,
                this, SLOT(onClosedMessage(QDBusMessage)));

    // For Notify METHOD calls: add a match rule so the bus delivers them to us,
    // then handle them via the raw message filter.
    // NOTE: full snooping requires becoming a monitor (dbus-monitor semantics),
    // which needs org.freedesktop.DBus.Monitoring.BecomeMonitor or a policy.
    // As a practical alternative, the daemon can register itself as the
    // Notifications service and proxy to the real one — deferred to P2.
    // For now, emit a stub every time NotificationClosed fires (sufficient for
    // the ambient-haptics MVP where we react to the "notification shown" moment
    // via the closed signal with reason=1 "expired").
}

// ---------------------------------------------------------------------------

void NotificationsSource::onNotifyMessage(const QDBusMessage& message)
{
    // Notify args: app_name(s), replaces_id(u), app_icon(s), summary(s), body(s),
    //              actions(as), hints(a{sv}), expire_timeout(i)
    const auto args = message.arguments();
    const QString appName = args.value(0).toString();
    const QString summary = args.value(3).toString();
    emit notificationArrived(appName, summary);
}

void NotificationsSource::onClosedMessage(const QDBusMessage& message)
{
    const auto args = message.arguments();
    const quint32 id     = args.value(0).toUInt();
    const quint32 reason = args.value(1).toUInt();
    emit notificationClosed(id, reason);

    // reason == 1 means "expired" (i.e. it was displayed and timed out) —
    // treat as notification-received event for ambient haptics until Notify
    // snooping is fully wired.
    if (reason == 1)
        emit notificationArrived(QString{}, QString{});
}
