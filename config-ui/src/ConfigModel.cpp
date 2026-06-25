#include "ConfigModel.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QProcess>
#include <QSaveFile>
#include <QSettings>
#include <QStandardPaths>
#include <QTextStream>

Q_LOGGING_CATEGORY(lcConfig, "mx4.config")

namespace mx4 {

namespace {

// -- configparser-compatible ordered INI ------------------------------------
// A minimal ordered INI model that round-trips with Python's configparser AND
// the overlay's QSettings reader: LITERAL section names (e.g. '[source:focus]')
// and LITERAL '/' in keys (e.g. 'center/command', '1/id'). Order of first
// appearance is preserved so unknown keys/sections survive a save unmoved.
class Ini
{
public:
    // Set (or insert) key=value under section, preserving insertion order.
    void set(const QString &section, const QString &key, const QString &value)
    {
        Section &sec = sectionRef(section);
        for (auto &kv : sec.entries) {
            if (kv.first == key) {
                kv.second = value;
                return;
            }
        }
        sec.entries.append({key, value});
    }

    // Drop the numeric '<n>/...' segment keys and 'count' from [radial] so a
    // shrunken menu leaves no stale higher-index slots. center/* + default_menu
    // and any unknown keys are kept.
    void removeRadialSegmentKeys()
    {
        const int idx = indexOf(QStringLiteral("radial"));
        if (idx < 0) {
            return;
        }
        QList<QPair<QString, QString>> kept;
        for (const auto &kv : m_sections[idx].entries) {
            const QString &k = kv.first;
            if (k == QLatin1String("count")) {
                continue; // rewritten below
            }
            // Drop keys whose first '/'-segment is a number ('3/id' etc.).
            const int slash = k.indexOf(QLatin1Char('/'));
            bool numericSlot = false;
            if (slash > 0) {
                k.left(slash).toInt(&numericSlot);
            }
            if (numericSlot) {
                continue;
            }
            kept.append(kv);
        }
        m_sections[idx].entries = kept;
    }

    // Serialize in configparser's style: "[section]\nkey = value\n\n".
    bool write(const QString &path) const
    {
        QSaveFile f(path);
        if (!f.open(QIODevice::WriteOnly | QIODevice::Text)) {
            return false;
        }
        QTextStream out(&f);
        for (int i = 0; i < m_sections.size(); ++i) {
            const Section &sec = m_sections.at(i);
            out << QLatin1Char('[') << sec.name << QLatin1Char(']') << '\n';
            for (const auto &kv : sec.entries) {
                out << kv.first << QStringLiteral(" = ") << kv.second << '\n';
            }
            out << '\n';
        }
        out.flush();
        return f.commit();
    }

private:
    struct Section
    {
        QString name;
        QList<QPair<QString, QString>> entries;
    };

    int indexOf(const QString &name) const
    {
        for (int i = 0; i < m_sections.size(); ++i) {
            if (m_sections.at(i).name == name) {
                return i;
            }
        }
        return -1;
    }
    Section &sectionRef(const QString &name)
    {
        const int i = indexOf(name);
        if (i >= 0) {
            return m_sections[i];
        }
        m_sections.append(Section{name, {}});
        return m_sections.last();
    }

    QList<Section> m_sections;
    friend Ini parseRawIni(const QString &path);
};

// Parse an existing INI into the ordered model, preserving unknown content.
// Comment/blank lines are dropped (as configparser does on write); keys keep
// their literal text (no escaping), so 'center/command' and '[source:focus]'
// pass through verbatim.
Ini parseRawIni(const QString &path)
{
    Ini ini;
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return ini; // absent/unreadable -> empty model (defaults get written)
    }
    QTextStream in(&f);
    QString current;
    while (!in.atEnd()) {
        QString line = in.readLine();
        const QString trimmed = line.trimmed();
        if (trimmed.isEmpty() || trimmed.startsWith(QLatin1Char('#'))
            || trimmed.startsWith(QLatin1Char(';'))) {
            continue;
        }
        if (trimmed.startsWith(QLatin1Char('[')) && trimmed.endsWith(QLatin1Char(']'))) {
            current = trimmed.mid(1, trimmed.size() - 2);
            ini.sectionRef(current); // create empty section, keep order
            continue;
        }
        const int eq = line.indexOf(QLatin1Char('='));
        if (eq < 0 || current.isEmpty()) {
            continue;
        }
        const QString key = line.left(eq).trimmed();
        const QString value = line.mid(eq + 1).trimmed();
        ini.set(current, key, value);
    }
    return ini;
}


// The full, ORDERED waveform name set. Mirrors daemon/mx4d/haptics.py WAVEFORMS
// (name -> index); kept in index order so the picker reads naturally. Which of
// these the firmware actually supports is reported separately by the daemon's
// capability mask (see DaemonBridge); the picker shows all + marks supported.
const QStringList kWaveformNames = {
    QStringLiteral("SHARP_STATE_CHANGE"),  // 0x00
    QStringLiteral("DAMP_STATE_CHANGE"),   // 0x01
    QStringLiteral("SHARP_COLLISION"),     // 0x02
    QStringLiteral("DAMP_COLLISION"),      // 0x03
    QStringLiteral("SUBTLE_COLLISION"),    // 0x04
    QStringLiteral("HAPPY_ALERT"),         // 0x05
    QStringLiteral("ANGRY_ALERT"),         // 0x06
    QStringLiteral("COMPLETED"),           // 0x07
    QStringLiteral("SQUARE"),              // 0x08
    QStringLiteral("WAVE"),                // 0x09
    QStringLiteral("FIREWORK"),            // 0x0A
    QStringLiteral("MAD"),                 // 0x0B
    QStringLiteral("KNOCK"),               // 0x0C
    QStringLiteral("JINGLE"),              // 0x0D
    QStringLiteral("RINGING"),             // 0x0E
    QStringLiteral("WHISPER_COLLISION"),   // 0x1B
};

// The three ambient source kinds, in the order the daemon builds them.
const QStringList kSourceKinds = {
    QStringLiteral("notification"),
    QStringLiteral("focus"),
    QStringLiteral("sound"),
};

bool toBool(const QVariant &v, bool fallback)
{
    if (!v.isValid()) {
        return fallback;
    }
    const QString s = v.toString().trimmed().toLower();
    return s == QLatin1String("1") || s == QLatin1String("true")
        || s == QLatin1String("yes") || s == QLatin1String("on");
}

QString boolStr(bool v)
{
    // Match config.py's _b(): lowercase "true"/"false".
    return v ? QStringLiteral("true") : QStringLiteral("false");
}

// First-on-PATH task manager command. MUST match config.py / MenuConfig.cpp
// ordering so the GUI's default center action agrees with both processes.
QString detectTaskManager()
{
    static const QVector<QStringList> candidates = {
        {QStringLiteral("plasma-systemmonitor")},
        {QStringLiteral("qps")},
        {QStringLiteral("lxtask")},
        {QStringLiteral("gnome-system-monitor")},
        {QStringLiteral("ksysguard")},
        {QStringLiteral("xterm"), QStringLiteral("-e"), QStringLiteral("htop")},
    };
    for (const QStringList &argv : candidates) {
        if (!QStandardPaths::findExecutable(argv.first()).isEmpty()) {
            return argv.join(QLatin1Char(' '));
        }
    }
    return QStringLiteral("xterm -e htop");
}

} // namespace

ConfigModel::ConfigModel(QObject *parent)
    : QObject(parent)
{
    load();
}

QString ConfigModel::configPath()
{
    // Same resolution the overlay uses (QStandardPaths honours XDG_CONFIG_HOME),
    // so all three processes read/write the identical file.
    const QString base =
        QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation);
    return QDir(base).filePath(QStringLiteral("mx4desktop/config.ini"));
}

QStringList ConfigModel::waveformNames() const
{
    return kWaveformNames;
}

void ConfigModel::load()
{
    const QString path = configPath();
    const bool exists = QFileInfo::exists(path);
    QSettings ini(path, QSettings::IniFormat);

    // [ambient]
    m_ambientEnabled = toBool(ini.value(QStringLiteral("ambient/enabled")), true);
    m_quietHours = toBool(ini.value(QStringLiteral("ambient/quiet_hours")), false);
    m_debounceInterval =
        ini.value(QStringLiteral("ambient/debounce_interval"), 0.12).toDouble();
    // Global haptic level: our own preserved key (daemon ignores unknown keys);
    // also driveable live via Daemon.SetLevel.
    m_hapticLevel = ini.value(QStringLiteral("ambient/haptic_level"), 60).toInt();

    // per-source
    m_sourceList.clear();
    const QStringList defWf = {QStringLiteral("HAPPY_ALERT"),
                               QStringLiteral("SUBTLE_COLLISION"),
                               QStringLiteral("DAMP_COLLISION")};
    const QList<int> defInt = {70, 40, 50};
    const QList<bool> defEn = {true, true, false};
    for (int i = 0; i < kSourceKinds.size(); ++i) {
        const QString kind = kSourceKinds.at(i);
        const QString g = QStringLiteral("source:") + kind + QLatin1Char('/');
        Source s;
        s.kind = kind;
        s.enabled = toBool(ini.value(g + QStringLiteral("enabled")), defEn.at(i));
        s.waveform =
            ini.value(g + QStringLiteral("waveform"), defWf.at(i)).toString();
        s.intensity =
            ini.value(g + QStringLiteral("intensity"), defInt.at(i)).toInt();
        m_sourceList.push_back(s);
    }

    // [trigger]
    m_divertPanel = toBool(ini.value(QStringLiteral("trigger/divert_panel")), true);
    m_triggerWaveform = ini.value(QStringLiteral("trigger/waveform"),
                                  QStringLiteral("HAPPY_ALERT")).toString();

    // [radial] center
    QString center = ini.value(QStringLiteral("radial/center/command")).toString();
    if (center.trimmed().isEmpty()) {
        // legacy key, then auto-detect (mirrors config.py's fallback chain).
        center = ini.value(QStringLiteral("radial/center_action")).toString();
    }
    if (center.trimmed().isEmpty()) {
        center = detectTaskManager();
    }
    m_centerCommand = center;
    m_centerLabel = ini.value(QStringLiteral("radial/center/label"),
                              QStringLiteral("Task Manager")).toString();
    m_centerIcon = ini.value(QStringLiteral("radial/center/icon"),
                             QStringLiteral("utilities-system-monitor")).toString();
    m_defaultMenu = ini.value(QStringLiteral("radial/default_menu"),
                              QStringLiteral("default")).toString();

    // [radial] segments
    m_segmentList.clear();
    const int count = ini.value(QStringLiteral("radial/count"), 0).toInt();
    for (int i = 1; i <= count; ++i) {
        const QString p = QStringLiteral("radial/") + QString::number(i)
            + QLatin1Char('/');
        Segment seg;
        seg.id = ini.value(p + QStringLiteral("id"),
                           QStringLiteral("slot%1").arg(i)).toString();
        seg.label = ini.value(p + QStringLiteral("label"),
                              QStringLiteral("Slot %1").arg(i)).toString();
        seg.icon = ini.value(p + QStringLiteral("icon"),
                             QStringLiteral("application-x-executable")).toString();
        seg.command = ini.value(p + QStringLiteral("command")).toString();
        seg.actionType = seg.command.trimmed().isEmpty()
            ? QStringLiteral("noop")
            : QStringLiteral("command");
        m_segmentList.push_back(seg);
    }
    // If the file had no segments at all, seed the same built-in default ring the
    // overlay would show, so the editor opens with something useful (mirrors
    // MenuConfig::loadBuiltinDefault). A SAVE then persists it explicitly.
    if (!exists || m_segmentList.isEmpty()) {
        m_segmentList = {
            {QStringLiteral("launcher"), QStringLiteral("Launcher"),
             QStringLiteral("system-run"), QStringLiteral("command"),
             QStringLiteral("krunner")},
            {QStringLiteral("switchdesktop"), QStringLiteral("Next Desktop"),
             QStringLiteral("virtual-desktops"), QStringLiteral("command"),
             QStringLiteral("qdbus6 org.kde.KWin /KWin nextDesktop")},
            {QStringLiteral("playpause"), QStringLiteral("Play / Pause"),
             QStringLiteral("media-playback-start"), QStringLiteral("command"),
             QStringLiteral("playerctl play-pause")},
            {QStringLiteral("lock"), QStringLiteral("Lock Screen"),
             QStringLiteral("system-lock-screen"), QStringLiteral("command"),
             QStringLiteral("loginctl lock-session")},
            {QStringLiteral("terminal"), QStringLiteral("Terminal"),
             QStringLiteral("utilities-terminal"), QStringLiteral("command"),
             QStringLiteral("xterm")},
            {QStringLiteral("custom"), QStringLiteral("Custom"),
             QStringLiteral("application-x-executable"), QStringLiteral("noop"),
             QString()},
        };
    }

    // [overlay]
    m_overlayCommand = ini.value(QStringLiteral("overlay/command"),
                                 QStringLiteral("mx4-radial")).toString();

    rebuildSourcesMirror();
    rebuildSegmentsMirror();

    m_dirty = false;
    emit changed();
    emit sourcesChanged();
    emit segmentsChanged();
    emit dirtyChanged();
    qCInfo(lcConfig) << "loaded config from" << path
                     << (exists ? "(existing)" : "(defaults; file absent)");
}

void ConfigModel::revert()
{
    load();
}

bool ConfigModel::save()
{
    const QString path = configPath();
    QDir().mkpath(QFileInfo(path).absolutePath());

    // CRITICAL: we DO NOT write via QSettings IniFormat here, because QSettings
    // escapes section names ('[source:focus]' -> '[source%3Afocus]') and uses
    // '\' as the key subgroup separator ('center\command'). The Python daemon
    // (configparser) needs LITERAL '[source:focus]' and 'center/command', so a
    // QSettings-written file is unreadable by the daemon. We therefore emit a
    // configparser-compatible INI by hand. (Reading via QSettings is fine — it
    // parses both the literal and the escaped forms; only its WRITING diverges.)
    //
    // Unknown sections/keys are preserved: we parse the existing raw file into
    // an ordered model, override only the keys we manage, then re-serialize.
    Ini ini = parseRawIni(path);

    ini.set(QStringLiteral("ambient"), QStringLiteral("enabled"),
            boolStr(m_ambientEnabled));
    ini.set(QStringLiteral("ambient"), QStringLiteral("quiet_hours"),
            boolStr(m_quietHours));
    ini.set(QStringLiteral("ambient"), QStringLiteral("debounce_interval"),
            QString::number(m_debounceInterval));
    ini.set(QStringLiteral("ambient"), QStringLiteral("haptic_level"),
            QString::number(m_hapticLevel));

    for (const Source &s : m_sourceList) {
        const QString sec = QStringLiteral("source:") + s.kind;
        ini.set(sec, QStringLiteral("enabled"), boolStr(s.enabled));
        ini.set(sec, QStringLiteral("waveform"), s.waveform);
        ini.set(sec, QStringLiteral("intensity"), QString::number(s.intensity));
    }

    ini.set(QStringLiteral("trigger"), QStringLiteral("divert_panel"),
            boolStr(m_divertPanel));
    ini.set(QStringLiteral("trigger"), QStringLiteral("waveform"),
            m_triggerWaveform);

    // [radial] center + default + the segment list. We first drop any stale
    // numeric '<n>/...' keys (from a previously larger menu) so a removed slot
    // never lingers, then rewrite count + 1..count.
    ini.removeRadialSegmentKeys();
    ini.set(QStringLiteral("radial"), QStringLiteral("center/command"),
            m_centerCommand);
    ini.set(QStringLiteral("radial"), QStringLiteral("center/label"),
            m_centerLabel);
    ini.set(QStringLiteral("radial"), QStringLiteral("center/icon"),
            m_centerIcon);
    ini.set(QStringLiteral("radial"), QStringLiteral("default_menu"),
            m_defaultMenu);
    ini.set(QStringLiteral("radial"), QStringLiteral("count"),
            QString::number(m_segmentList.size()));
    for (int i = 0; i < m_segmentList.size(); ++i) {
        const Segment &seg = m_segmentList.at(i);
        const QString p = QString::number(i + 1) + QLatin1Char('/');
        ini.set(QStringLiteral("radial"), p + QStringLiteral("id"), seg.id);
        ini.set(QStringLiteral("radial"), p + QStringLiteral("label"), seg.label);
        ini.set(QStringLiteral("radial"), p + QStringLiteral("icon"), seg.icon);
        // A "noop" segment writes an empty command (the overlay reads an empty
        // command as noop), so the round-trip is exact.
        const QString cmd = seg.actionType == QLatin1String("noop")
            ? QString()
            : seg.command;
        ini.set(QStringLiteral("radial"), p + QStringLiteral("command"), cmd);
    }

    ini.set(QStringLiteral("overlay"), QStringLiteral("command"),
            m_overlayCommand);

    if (!ini.write(path)) {
        qCWarning(lcConfig) << "save failed writing" << path;
        return false;
    }
    m_dirty = false;
    emit dirtyChanged();
    qCInfo(lcConfig) << "saved config to" << path;
    return true;
}

void ConfigModel::markDirty()
{
    if (!m_dirty) {
        m_dirty = true;
        emit dirtyChanged();
    }
}

void ConfigModel::rebuildSourcesMirror()
{
    m_sources.clear();
    for (const Source &s : m_sourceList) {
        QVariantMap m;
        m.insert(QStringLiteral("kind"), s.kind);
        m.insert(QStringLiteral("enabled"), s.enabled);
        m.insert(QStringLiteral("waveform"), s.waveform);
        m.insert(QStringLiteral("intensity"), s.intensity);
        m_sources.push_back(m);
    }
}

void ConfigModel::rebuildSegmentsMirror()
{
    m_segments.clear();
    for (const Segment &seg : m_segmentList) {
        QVariantMap m;
        m.insert(QStringLiteral("id"), seg.id);
        m.insert(QStringLiteral("label"), seg.label);
        m.insert(QStringLiteral("icon"), seg.icon);
        m.insert(QStringLiteral("actionType"), seg.actionType);
        m.insert(QStringLiteral("command"), seg.command);
        m_segments.push_back(m);
    }
}

int ConfigModel::sourceIndex(const QString &kind) const
{
    for (int i = 0; i < m_sourceList.size(); ++i) {
        if (m_sourceList.at(i).kind == kind) {
            return i;
        }
    }
    return -1;
}

// -- scalar setters ----------------------------------------------------------

void ConfigModel::setAmbientEnabled(bool v)
{
    if (m_ambientEnabled == v) return;
    m_ambientEnabled = v; markDirty(); emit changed();
}
void ConfigModel::setQuietHours(bool v)
{
    if (m_quietHours == v) return;
    m_quietHours = v; markDirty(); emit changed();
}
void ConfigModel::setDebounceInterval(double v)
{
    if (qFuzzyCompare(m_debounceInterval, v)) return;
    m_debounceInterval = v; markDirty(); emit changed();
}
void ConfigModel::setHapticLevel(int v)
{
    v = qBound(0, v, 100);
    if (m_hapticLevel == v) return;
    m_hapticLevel = v; markDirty(); emit changed();
}
void ConfigModel::setDivertPanel(bool v)
{
    if (m_divertPanel == v) return;
    m_divertPanel = v; markDirty(); emit changed();
}
void ConfigModel::setTriggerWaveform(const QString &v)
{
    if (m_triggerWaveform == v) return;
    m_triggerWaveform = v; markDirty(); emit changed();
}
void ConfigModel::setCenterCommand(const QString &v)
{
    if (m_centerCommand == v) return;
    m_centerCommand = v; markDirty(); emit changed();
}
void ConfigModel::setCenterLabel(const QString &v)
{
    if (m_centerLabel == v) return;
    m_centerLabel = v; markDirty(); emit changed();
}
void ConfigModel::setCenterIcon(const QString &v)
{
    if (m_centerIcon == v) return;
    m_centerIcon = v; markDirty(); emit changed();
}
void ConfigModel::setDefaultMenu(const QString &v)
{
    if (m_defaultMenu == v) return;
    m_defaultMenu = v; markDirty(); emit changed();
}
void ConfigModel::setOverlayCommand(const QString &v)
{
    if (m_overlayCommand == v) return;
    m_overlayCommand = v; markDirty(); emit changed();
}

// -- per-source mutators -----------------------------------------------------

void ConfigModel::setSourceEnabled(const QString &kind, bool enabled)
{
    const int i = sourceIndex(kind);
    if (i < 0 || m_sourceList[i].enabled == enabled) return;
    m_sourceList[i].enabled = enabled;
    rebuildSourcesMirror();
    markDirty();
    emit sourcesChanged();
}
void ConfigModel::setSourceWaveform(const QString &kind, const QString &waveform)
{
    const int i = sourceIndex(kind);
    if (i < 0 || m_sourceList[i].waveform == waveform) return;
    m_sourceList[i].waveform = waveform;
    rebuildSourcesMirror();
    markDirty();
    emit sourcesChanged();
}
void ConfigModel::setSourceIntensity(const QString &kind, int intensity)
{
    const int i = sourceIndex(kind);
    intensity = qBound(0, intensity, 100);
    if (i < 0 || m_sourceList[i].intensity == intensity) return;
    m_sourceList[i].intensity = intensity;
    rebuildSourcesMirror();
    markDirty();
    emit sourcesChanged();
}

// -- segment editing ---------------------------------------------------------

void ConfigModel::addSegment()
{
    Segment seg;
    const int n = m_segmentList.size() + 1;
    seg.id = QStringLiteral("slot%1").arg(n);
    seg.label = QStringLiteral("New Action");
    seg.icon = QStringLiteral("application-x-executable");
    seg.actionType = QStringLiteral("noop");
    seg.command = QString();
    m_segmentList.push_back(seg);
    rebuildSegmentsMirror();
    markDirty();
    emit segmentsChanged();
}

void ConfigModel::removeSegment(int index)
{
    if (index < 0 || index >= m_segmentList.size()) return;
    m_segmentList.removeAt(index);
    rebuildSegmentsMirror();
    markDirty();
    emit segmentsChanged();
}

void ConfigModel::moveSegment(int from, int to)
{
    if (from < 0 || from >= m_segmentList.size()) return;
    if (to < 0 || to >= m_segmentList.size() || to == from) return;
    m_segmentList.move(from, to);
    rebuildSegmentsMirror();
    markDirty();
    emit segmentsChanged();
}

void ConfigModel::setSegmentField(int index, const QString &field,
                                  const QString &value)
{
    if (index < 0 || index >= m_segmentList.size()) return;
    Segment &seg = m_segmentList[index];
    if (field == QLatin1String("id")) {
        if (seg.id == value) return;
        seg.id = value;
    } else if (field == QLatin1String("label")) {
        if (seg.label == value) return;
        seg.label = value;
    } else if (field == QLatin1String("icon")) {
        if (seg.icon == value) return;
        seg.icon = value;
    } else if (field == QLatin1String("actionType")) {
        if (seg.actionType == value) return;
        seg.actionType = value;
    } else if (field == QLatin1String("command")) {
        if (seg.command == value) return;
        seg.command = value;
    } else {
        return;
    }
    rebuildSegmentsMirror();
    markDirty();
    emit segmentsChanged();
}

} // namespace mx4
