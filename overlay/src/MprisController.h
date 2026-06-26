#ifndef MX4_MPRISCONTROLLER_H
#define MX4_MPRISCONTROLLER_H

#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantMap>

class QTimer;

namespace mx4 {

/**
 * Minimal MPRIS2 client backing the media-controls panel. Finds the active
 * org.mpris.MediaPlayer2.* player on the session bus, exposes its metadata
 * (title / artist / art / length), playback state and position to QML, and
 * drives PlayPause / Next / Previous / SetPosition. It live-updates from the
 * player's PropertiesChanged signal and a position poll timer while playing.
 *
 * Everything is best-effort: with no player present ``available`` is false and
 * the panel shows a "nothing playing" state. All reads/calls are on the session
 * bus the overlay already uses.
 */
class MprisController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool available READ available NOTIFY changed)
    Q_PROPERTY(QString title READ title NOTIFY changed)
    Q_PROPERTY(QString artist READ artist NOTIFY changed)
    Q_PROPERTY(QString artUrl READ artUrl NOTIFY changed)
    Q_PROPERTY(QString playerName READ playerName NOTIFY changed)
    Q_PROPERTY(bool playing READ playing NOTIFY changed)
    Q_PROPERTY(bool canGoNext READ canGoNext NOTIFY changed)
    Q_PROPERTY(bool canGoPrevious READ canGoPrevious NOTIFY changed)
    Q_PROPERTY(bool canSeek READ canSeek NOTIFY changed)
    // Times are MPRIS microseconds.
    Q_PROPERTY(qlonglong position READ position NOTIFY positionChanged)
    Q_PROPERTY(qlonglong length READ length NOTIFY changed)
    // Thumb seek-scrub preview: while scrubbing, the QML draws the bar at
    // scrubPosition instead of the live position (committed on release).
    Q_PROPERTY(bool scrubbing READ scrubbing NOTIFY positionChanged)
    Q_PROPERTY(qlonglong scrubPosition READ scrubPosition NOTIFY positionChanged)

public:
    explicit MprisController(QObject *parent = nullptr);

    bool available() const { return !m_service.isEmpty(); }
    QString title() const { return m_title; }
    QString artist() const { return m_artist; }
    QString artUrl() const { return m_artUrl; }
    QString playerName() const { return m_playerName; }
    bool playing() const { return m_playing; }
    bool canGoNext() const { return m_canGoNext; }
    bool canGoPrevious() const { return m_canGoPrevious; }
    bool canSeek() const { return m_canSeek; }
    qlonglong position() const { return m_position; }
    qlonglong length() const { return m_length; }
    bool scrubbing() const { return m_scrubbing; }
    qlonglong scrubPosition() const { return m_scrubPosition; }

public slots:
    // Re-scan for the active player and refresh everything (call on panel show).
    void refresh();
    // Stop the position poll (call when the panel hides) so we don't tick idle.
    void suspend();
    void playPause();
    void next();
    void previous();
    // Seek to an absolute position (microseconds) via Player.SetPosition.
    void seekTo(qlonglong positionUs);
    // Thumb seek-scrub: preview a seek by a net horizontal slide (raw sensor
    // units, relative to the position when scrubbing began). commitScrub()
    // applies the previewed position via SetPosition; both are no-ops if the
    // player cannot seek.
    void scrubBy(int dx);
    void commitScrub();
    // Ask the host to close the panel (Escape / click-outside / close button).
    void dismiss();

signals:
    void changed();          // metadata / capabilities / play-state changed
    void positionChanged();  // the playback position advanced
    void dismissRequested(); // the panel asked to close

private slots:
    void onPropertiesChanged(const QString &iface, const QVariantMap &changed,
                             const QStringList &invalidated);
    void pollPosition();

private:
    void pickPlayer();    // choose the active org.mpris.* service (prefer Playing)
    void readAll();       // read metadata + status + caps + position
    QVariant playerProp(const QString &name) const; // Properties.Get on Player

    QString m_service;    // org.mpris.MediaPlayer2.<player> ("" = none)
    QString m_playerName;
    QString m_title;
    QString m_artist;
    QString m_artUrl;
    QString m_trackId;    // mpris:trackid object path (for SetPosition)
    bool m_playing = false;
    bool m_canGoNext = false;
    bool m_canGoPrevious = false;
    bool m_canSeek = false;
    qlonglong m_position = 0;
    qlonglong m_length = 0;
    // Seek-scrub preview state (see scrubBy/commitScrub).
    bool m_scrubbing = false;
    qlonglong m_scrubStart = 0;    // position captured when scrubbing began
    qlonglong m_scrubPosition = 0; // current previewed position
    QTimer *m_pollTimer;
};

} // namespace mx4

#endif // MX4_MPRISCONTROLLER_H
