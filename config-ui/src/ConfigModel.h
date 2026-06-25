#ifndef MX4_CONFIGMODEL_H
#define MX4_CONFIGMODEL_H

#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

class QSettings;

namespace mx4 {

/**
 * ConfigModel — the QML-facing read/write view over the SHARED INI at
 * ``~/.config/mx4desktop/config.ini`` (honouring ``XDG_CONFIG_HOME``).
 *
 * It writes the EXACT same sections / keys / value formats that the Python
 * daemon (``daemon/mx4d/config.py``) and the C++ overlay
 * (``overlay/src/MenuConfig.cpp``) parse, so a file this GUI saves is loadable
 * by BOTH processes. The schema (verified against both parsers):
 *
 *   [ambient]               enabled, quiet_hours (true/false); debounce_interval (float)
 *   [source:notification]   enabled (true/false); waveform (name); intensity (0..100)
 *   [source:focus]          "
 *   [source:sound]          "
 *   [trigger]               divert_panel (true/false); waveform (name)
 *   [radial]                center/command (QProcess::splitCommand argv, NO shell),
 *                           center/label, center/icon, default_menu,
 *                           count (int), and per-segment <n>/id, <n>/label,
 *                           <n>/icon, <n>/command  for n = 1..count
 *   [overlay]               command (daemon's lazy-launch command)
 *
 * READING uses QSettings IniFormat (whose '/' group separator parses the
 * literal ``center/command`` / ``1/id`` keys, and which also tolerates the
 * escaped forms QSettings itself would emit).
 *
 * WRITING does NOT use QSettings: its IniFormat writer escapes section names
 * (``[source:focus]`` -> ``[source%3Afocus]``) and uses '\\' as the key
 * subgroup separator (``center\command``), which the Python daemon's
 * configparser cannot read. So save() hand-emits a configparser-compatible INI
 * (literal ':' in section names, literal '/' in keys) via an ordered model.
 *
 * Unknown keys/sections are PRESERVED on save: that ordered model is seeded by
 * re-parsing the existing raw file, and save() only overrides the keys we
 * manage, leaving every other section/key untouched and in place.
 *
 * The model holds an in-memory working copy (apply/revert via a dirty flag);
 * save() flushes the working copy to disk.
 */
class ConfigModel : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool dirty READ dirty NOTIFY dirtyChanged)
    Q_PROPERTY(QString configPath READ configPath CONSTANT)

    // [ambient]
    Q_PROPERTY(bool ambientEnabled READ ambientEnabled WRITE setAmbientEnabled NOTIFY changed)
    Q_PROPERTY(bool quietHours READ quietHours WRITE setQuietHours NOTIFY changed)
    Q_PROPERTY(double debounceInterval READ debounceInterval WRITE setDebounceInterval NOTIFY changed)

    // Global haptic level (0..100). Persisted as our own [ambient] haptic_level
    // key (the daemon ignores unknown keys) and pushable to the device live via
    // Daemon.SetLevel. It is NOT a per-source intensity — those are separate.
    Q_PROPERTY(int hapticLevel READ hapticLevel WRITE setHapticLevel NOTIFY changed)

    // [trigger]
    // divertPanel is TRI-STATE: "auto" (defer to Solaar if running) / "true"
    // (always capture, standalone) / "false" (never capture, Solaar handles it).
    // Kept as a string so the GUI reads AND writes "auto" without a bool toggle
    // silently coercing it to "false".
    Q_PROPERTY(QString divertPanel READ divertPanel WRITE setDivertPanel NOTIFY changed)
    Q_PROPERTY(QString triggerWaveform READ triggerWaveform WRITE setTriggerWaveform NOTIFY changed)

    // [radial] center
    Q_PROPERTY(QString centerCommand READ centerCommand WRITE setCenterCommand NOTIFY changed)
    Q_PROPERTY(QString centerLabel READ centerLabel WRITE setCenterLabel NOTIFY changed)
    Q_PROPERTY(QString centerIcon READ centerIcon WRITE setCenterIcon NOTIFY changed)
    Q_PROPERTY(QString defaultMenu READ defaultMenu WRITE setDefaultMenu NOTIFY changed)

    // [overlay]
    Q_PROPERTY(QString overlayCommand READ overlayCommand WRITE setOverlayCommand NOTIFY changed)

    // per-source list + radial segment list (QML-friendly mirrors)
    Q_PROPERTY(QVariantList sources READ sources NOTIFY sourcesChanged)
    Q_PROPERTY(QVariantList segments READ segments NOTIFY segmentsChanged)

    // The full, ordered waveform name set (for the picker combos).
    Q_PROPERTY(QStringList waveformNames READ waveformNames CONSTANT)

public:
    explicit ConfigModel(QObject *parent = nullptr);

    static QString configPath();

    bool dirty() const { return m_dirty; }

    bool ambientEnabled() const { return m_ambientEnabled; }
    bool quietHours() const { return m_quietHours; }
    double debounceInterval() const { return m_debounceInterval; }
    int hapticLevel() const { return m_hapticLevel; }
    QString divertPanel() const { return m_divertPanel; }
    QString triggerWaveform() const { return m_triggerWaveform; }
    QString centerCommand() const { return m_centerCommand; }
    QString centerLabel() const { return m_centerLabel; }
    QString centerIcon() const { return m_centerIcon; }
    QString defaultMenu() const { return m_defaultMenu; }
    QString overlayCommand() const { return m_overlayCommand; }
    QVariantList sources() const { return m_sources; }
    QVariantList segments() const { return m_segments; }
    QStringList waveformNames() const;

    void setAmbientEnabled(bool v);
    void setQuietHours(bool v);
    void setDebounceInterval(double v);
    void setHapticLevel(int v);
    void setDivertPanel(const QString &v);
    void setTriggerWaveform(const QString &v);
    void setCenterCommand(const QString &v);
    void setCenterLabel(const QString &v);
    void setCenterIcon(const QString &v);
    void setDefaultMenu(const QString &v);
    void setOverlayCommand(const QString &v);

public slots:
    // (Re)load the working copy from disk (or built-in defaults if absent).
    void load();
    // Discard in-memory edits and reload from disk.
    void revert();
    // Flush the working copy to disk, preserving unknown keys.
    bool save();

    // -- per-source mutators (kind = "notification" | "focus" | "sound") -----
    void setSourceEnabled(const QString &kind, bool enabled);
    void setSourceWaveform(const QString &kind, const QString &waveform);
    void setSourceIntensity(const QString &kind, int intensity);

    // -- radial segment list editing -----------------------------------------
    void addSegment();
    void removeSegment(int index);
    void moveSegment(int from, int to);
    void setSegmentField(int index, const QString &field, const QString &value);

signals:
    void changed();
    void dirtyChanged();
    void sourcesChanged();
    void segmentsChanged();

private:
    void markDirty();
    void rebuildSourcesMirror();
    void rebuildSegmentsMirror();
    int sourceIndex(const QString &kind) const;

    // Working-copy structs (mirror the typed config the other parsers build).
    struct Source
    {
        QString kind;     // "notification" | "focus" | "sound"
        bool enabled = true;
        QString waveform; // a waveform NAME
        int intensity = 50;
    };
    struct Segment
    {
        QString id;
        QString label;
        QString icon;
        QString actionType; // "command" | "noop"
        QString command;    // raw command string (QProcess::splitCommand on read)
    };

    // [ambient]
    bool m_ambientEnabled = true;
    bool m_quietHours = false;
    double m_debounceInterval = 0.12;
    int m_hapticLevel = 60;
    // [trigger] — tri-state "auto"/"true"/"false" (default "auto").
    QString m_divertPanel = QStringLiteral("auto");
    QString m_triggerWaveform = QStringLiteral("HAPPY_ALERT");
    // [radial]
    QString m_centerCommand;
    QString m_centerLabel = QStringLiteral("Task Manager");
    QString m_centerIcon = QStringLiteral("utilities-system-monitor");
    QString m_defaultMenu = QStringLiteral("default");
    // [overlay]
    QString m_overlayCommand = QStringLiteral("mx4-radial");

    QList<Source> m_sourceList;
    QList<Segment> m_segmentList;

    QVariantList m_sources;  // QML mirror of m_sourceList
    QVariantList m_segments; // QML mirror of m_segmentList

    bool m_dirty = false;
};

} // namespace mx4

#endif // MX4_CONFIGMODEL_H
