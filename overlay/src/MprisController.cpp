#include "MprisController.h"

#include <QDBusArgument>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusMetaType>
#include <QDBusObjectPath>
#include <QDBusReply>
#include <QLoggingCategory>
#include <QTimer>

Q_LOGGING_CATEGORY(lcMpris, "mx4.mpris")

namespace mx4 {

namespace {
constexpr auto kMprisPrefix = "org.mpris.MediaPlayer2.";
constexpr auto kMprisPath = "/org/mpris/MediaPlayer2";
constexpr auto kPlayerIface = "org.mpris.MediaPlayer2.Player";
constexpr auto kPropsIface = "org.freedesktop.DBus.Properties";

// Player.PlaybackStatus / metadata reads time out fast so a wedged player can
// never stall the overlay's UI thread.
constexpr int kCallTimeoutMs = 400;
} // namespace

MprisController::MprisController(QObject *parent)
    : QObject(parent)
    , m_pollTimer(new QTimer(this))
{
    // While playing, advance the position bar without waiting for a player to
    // emit anything (most don't emit Position changes).
    m_pollTimer->setInterval(500);
    connect(m_pollTimer, &QTimer::timeout, this, &MprisController::pollPosition);
}

void MprisController::pickPlayer()
{
    QDBusConnection bus = QDBusConnection::sessionBus();

    // Drop any prior PropertiesChanged subscription before re-choosing.
    if (!m_service.isEmpty()) {
        bus.disconnect(m_service, QString::fromLatin1(kMprisPath),
                       QString::fromLatin1(kPropsIface),
                       QStringLiteral("PropertiesChanged"), this,
                       SLOT(onPropertiesChanged(QString, QVariantMap, QStringList)));
        m_service.clear();
    }

    if (!bus.interface()) {
        return;
    }
    const QDBusReply<QStringList> names = bus.interface()->registeredServiceNames();
    if (!names.isValid()) {
        return;
    }

    QString firstMpris;
    QString playingMpris;
    for (const QString &name : names.value()) {
        if (!name.startsWith(QLatin1String(kMprisPrefix))) {
            continue;
        }
        if (firstMpris.isEmpty()) {
            firstMpris = name;
        }
        QDBusInterface props(name, QString::fromLatin1(kMprisPath),
                             QString::fromLatin1(kPropsIface), bus);
        props.setTimeout(kCallTimeoutMs);
        const QDBusReply<QVariant> st =
            props.call(QStringLiteral("Get"), QString::fromLatin1(kPlayerIface),
                       QStringLiteral("PlaybackStatus"));
        if (st.isValid() && st.value().toString() == QLatin1String("Playing")) {
            playingMpris = name;
            break; // a playing player wins outright
        }
    }

    // Prefer the player that is actually playing; else the first one present.
    m_service = !playingMpris.isEmpty() ? playingMpris : firstMpris;
    if (m_service.isEmpty()) {
        m_playerName.clear();
        return;
    }
    // "org.mpris.MediaPlayer2.firefox.instance_1" -> "firefox".
    const int prefixLen = static_cast<int>(QString::fromLatin1(kMprisPrefix).length());
    m_playerName = m_service.mid(prefixLen).section(QLatin1Char('.'), 0, 0);
    bus.connect(m_service, QString::fromLatin1(kMprisPath),
                QString::fromLatin1(kPropsIface),
                QStringLiteral("PropertiesChanged"), this,
                SLOT(onPropertiesChanged(QString, QVariantMap, QStringList)));
    qCInfo(lcMpris) << "active player" << m_service;
}

QVariant MprisController::playerProp(const QString &name) const
{
    if (m_service.isEmpty()) {
        return {};
    }
    QDBusInterface props(m_service, QString::fromLatin1(kMprisPath),
                         QString::fromLatin1(kPropsIface),
                         QDBusConnection::sessionBus());
    props.setTimeout(kCallTimeoutMs);
    const QDBusReply<QVariant> reply = props.call(
        QStringLiteral("Get"), QString::fromLatin1(kPlayerIface), name);
    return reply.isValid() ? reply.value() : QVariant();
}

void MprisController::readAll()
{
    if (m_service.isEmpty()) {
        m_title.clear();
        m_artist.clear();
        m_artUrl.clear();
        m_trackId.clear();
        m_playing = false;
        m_canGoNext = m_canGoPrevious = m_canSeek = false;
        m_position = 0;
        m_length = 0;
        m_pollTimer->stop();
        emit changed();
        emit positionChanged();
        return;
    }

    const QVariantMap meta = qdbus_cast<QVariantMap>(playerProp(QStringLiteral("Metadata")));
    m_title = meta.value(QStringLiteral("xesam:title")).toString();
    m_artist = qdbus_cast<QStringList>(meta.value(QStringLiteral("xesam:artist")))
                   .join(QStringLiteral(", "));
    m_artUrl = meta.value(QStringLiteral("mpris:artUrl")).toString();
    m_length = meta.value(QStringLiteral("mpris:length")).toLongLong();
    m_trackId = meta.value(QStringLiteral("mpris:trackid"))
                    .value<QDBusObjectPath>()
                    .path();

    m_playing = playerProp(QStringLiteral("PlaybackStatus")).toString()
                == QLatin1String("Playing");
    m_canGoNext = playerProp(QStringLiteral("CanGoNext")).toBool();
    m_canGoPrevious = playerProp(QStringLiteral("CanGoPrevious")).toBool();
    m_canSeek = playerProp(QStringLiteral("CanSeek")).toBool();
    m_position = playerProp(QStringLiteral("Position")).toLongLong();

    if (m_playing) {
        m_pollTimer->start();
    } else {
        m_pollTimer->stop();
    }
    emit changed();
    emit positionChanged();
}

void MprisController::refresh()
{
    pickPlayer();
    readAll();
}

void MprisController::suspend()
{
    m_pollTimer->stop();
}

void MprisController::pollPosition()
{
    if (m_service.isEmpty()) {
        m_pollTimer->stop();
        return;
    }
    m_position = playerProp(QStringLiteral("Position")).toLongLong();
    emit positionChanged();
}

void MprisController::onPropertiesChanged(const QString &iface,
                                          const QVariantMap &changed,
                                          const QStringList &invalidated)
{
    Q_UNUSED(iface);
    Q_UNUSED(changed);
    Q_UNUSED(invalidated);
    // Cheap + robust: re-read the whole player state rather than diffing the
    // a{sv}. Players emit this on track/state changes, which is exactly when we
    // want a full refresh.
    readAll();
}

void MprisController::playPause()
{
    if (m_service.isEmpty()) {
        return;
    }
    QDBusInterface player(m_service, QString::fromLatin1(kMprisPath),
                          QString::fromLatin1(kPlayerIface),
                          QDBusConnection::sessionBus());
    player.asyncCall(QStringLiteral("PlayPause"));
    // The PlaybackStatus updates after the call; re-read shortly to flip the
    // play/pause icon even for players that don't emit PropertiesChanged.
    QTimer::singleShot(150, this, &MprisController::readAll);
}

void MprisController::next()
{
    if (m_service.isEmpty()) {
        return;
    }
    QDBusInterface player(m_service, QString::fromLatin1(kMprisPath),
                          QString::fromLatin1(kPlayerIface),
                          QDBusConnection::sessionBus());
    player.asyncCall(QStringLiteral("Next"));
    QTimer::singleShot(200, this, &MprisController::readAll);
}

void MprisController::previous()
{
    if (m_service.isEmpty()) {
        return;
    }
    QDBusInterface player(m_service, QString::fromLatin1(kMprisPath),
                          QString::fromLatin1(kPlayerIface),
                          QDBusConnection::sessionBus());
    player.asyncCall(QStringLiteral("Previous"));
    QTimer::singleShot(200, this, &MprisController::readAll);
}

void MprisController::seekTo(qlonglong positionUs)
{
    if (m_service.isEmpty() || !m_canSeek || m_trackId.isEmpty()) {
        return;
    }
    QDBusInterface player(m_service, QString::fromLatin1(kMprisPath),
                          QString::fromLatin1(kPlayerIface),
                          QDBusConnection::sessionBus());
    // SetPosition(o TrackId, x Position) — absolute seek, ignored by the player
    // if TrackId no longer matches the current track (safe).
    player.asyncCall(QStringLiteral("SetPosition"),
                     QVariant::fromValue(QDBusObjectPath(m_trackId)),
                     QVariant::fromValue<qlonglong>(positionUs));
    m_position = positionUs; // optimistic; corrected by the next poll/refresh
    emit positionChanged();
}

void MprisController::dismiss()
{
    emit dismissRequested();
}

} // namespace mx4
