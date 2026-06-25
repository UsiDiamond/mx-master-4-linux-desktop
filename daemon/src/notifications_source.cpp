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
    QDBusConnection::sessionBus().disconnect(
        NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, NOTIFY_METHOD,
        this, SLOT(onNotifyMessage(QDBusMessage)));
    QDBusConnection::sessionBus().disconnect(
        NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, CLOSED_SIGNAL,
        this, SLOT(onClosedMessage(QDBusMessage)));
}

// ---------------------------------------------------------------------------

void NotificationsSource::connectToSessionBus()
{
    // Monitor the NotificationClosed SIGNAL (standard DBus signal — works directly)
    QDBusConnection::sessionBus().connect(
        NOTIF_SERVICE, NOTIF_PATH, NOTIF_INTERFACE, CLOSED_SIGNAL,
        this, SLOT(onClosedMessage(QDBusMessage)));

    // Note: snooping Notify *method calls* requires BecomeMonitor or proxying the
    // Notifications service — deferred to P2.  For the ambient-haptics MVP we use
    // the NotificationClosed signal (reason=1 "expired") as a proxy for "shown".
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
