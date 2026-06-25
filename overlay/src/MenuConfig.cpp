#include "MenuConfig.h"

#include <QDir>
#include <QFileInfo>
#include <QProcess>
#include <QSettings>
#include <QStandardPaths>

namespace mx4 {

namespace {

// Resolve a program name against PATH (or accept an absolute path that exists).
bool onPath(const QString &program)
{
    if (program.isEmpty()) {
        return false;
    }
    if (QDir::isAbsolutePath(program)) {
        return QFileInfo(program).isExecutable();
    }
    return !QStandardPaths::findExecutable(program).isEmpty();
}

// Pick the qdbus binary that actually exists (Qt6 ships it as qdbus6 on many
// distros; older setups have qdbus). Falls back to "qdbus6" so the argv is
// still well-formed if neither is found (start simply fails & is logged).
QString qdbusBin()
{
    for (const auto &name : {QStringLiteral("qdbus6"), QStringLiteral("qdbus")}) {
        if (!QStandardPaths::findExecutable(name).isEmpty()) {
            return name;
        }
    }
    return QStringLiteral("qdbus6");
}

// First-on-PATH application launcher / "start menu" for this environment.
// krunner (KDE) does not exist on LXQt, so we probe a cross-desktop list and
// fall back to a terminal. Kept ordered so the result is deterministic.
QStringList detectAppLauncher()
{
    static const QVector<QStringList> candidates = {
        {QStringLiteral("krunner")},
        {QStringLiteral("lxqt-runner")},
        {QStringLiteral("rofi"), QStringLiteral("-show"), QStringLiteral("drun")},
        {QStringLiteral("wofi"), QStringLiteral("--show"), QStringLiteral("drun")},
        {QStringLiteral("ulauncher")},
        {QStringLiteral("albert"), QStringLiteral("toggle")},
        {QStringLiteral("xfce4-appfinder")},
        {QStringLiteral("synapse")},
        {QStringLiteral("gmrun")},
        {QStringLiteral("dmenu_run")},
    };
    for (const QStringList &argv : candidates) {
        if (onPath(argv.first())) {
            return argv;
        }
    }
    return {QStringLiteral("xterm")}; // last resort: a terminal to launch apps
}

// Quote-aware split with NO shell semantics. Empty/garbage yields {}.
QStringList splitCommand(const QString &command)
{
    const QString trimmed = command.trimmed();
    if (trimmed.isEmpty()) {
        return {};
    }
    return QProcess::splitCommand(trimmed);
}

} // namespace

MenuConfig::MenuConfig(const QString &menuId)
    : m_menuId(menuId)
{
    loadFromIniOrDefault();
}

QString MenuConfig::configPath()
{
    // Honour XDG_CONFIG_HOME via QStandardPaths; the daemon and the KCM write
    // the same file, so we never hardcode ~/.config.
    const QString base =
        QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation);
    return QDir(base).filePath(QStringLiteral("mx4desktop/config.ini"));
}

QStringList MenuConfig::detectTaskManager()
{
    // Ordered preference: Plasma -> LXQt -> generic -> terminal fallback. This
    // MUST match the daemon's config.py TASK_MANAGER_CANDIDATES order so both
    // processes pick the same center action: plasma-systemmonitor -> qps ->
    // lxtask -> gnome-system-monitor -> ksysguard (deprecated, last) -> htop.
    static const QVector<QStringList> candidates = {
        {QStringLiteral("plasma-systemmonitor")},
        {QStringLiteral("qps")},
        {QStringLiteral("lxtask")},
        {QStringLiteral("gnome-system-monitor")},
        {QStringLiteral("ksysguard")},
        {QStringLiteral("xterm"), QStringLiteral("-e"), QStringLiteral("htop")},
    };
    for (const QStringList &argv : candidates) {
        if (onPath(argv.first())) {
            return argv;
        }
    }
    // Last resort: still hand back something runnable-shaped.
    return {QStringLiteral("xterm"), QStringLiteral("-e"), QStringLiteral("htop")};
}

void MenuConfig::loadBuiltinDefault()
{
    const QStringList taskMgr = detectTaskManager();
    const QStringList appLauncher = detectAppLauncher();

    m_center = MenuItem{
        QStringLiteral("taskmanager"),
        QStringLiteral("Task Manager"),
        QStringLiteral("utilities-system-monitor"),
        QStringLiteral("command"),
        taskMgr,
    };

    // Sensible default ring (all user-editable later). Programs are launched
    // only if present; a missing program simply fails the QProcess start and
    // is logged, never crashes. The first slot is the auto-detected application
    // launcher / start menu, so the ring always "includes the app menu".
    m_segments = {
        {QStringLiteral("appmenu"), QStringLiteral("Applications"),
         QStringLiteral("applications-all"), QStringLiteral("command"),
         appLauncher},

        {QStringLiteral("switchdesktop"), QStringLiteral("Next Desktop"),
         QStringLiteral("virtual-desktops"), QStringLiteral("command"),
         // Portable-ish: try qdbus to bump KWin's current desktop; harmless no-op
         // elsewhere. Kept as an argv (no shell). Binary name resolved at
         // load time (qdbus6 on Qt6 distros, else qdbus).
         {qdbusBin(), QStringLiteral("org.kde.KWin"),
          QStringLiteral("/KWin"), QStringLiteral("nextDesktop")}},

        {QStringLiteral("playpause"), QStringLiteral("Play / Pause"),
         QStringLiteral("media-playback-start"), QStringLiteral("command"),
         {QStringLiteral("playerctl"), QStringLiteral("play-pause")}},

        {QStringLiteral("lock"), QStringLiteral("Lock Screen"),
         QStringLiteral("system-lock-screen"), QStringLiteral("command"),
         {QStringLiteral("loginctl"), QStringLiteral("lock-session")}},

        {QStringLiteral("terminal"), QStringLiteral("Terminal"),
         QStringLiteral("utilities-terminal"), QStringLiteral("command"),
         {QStringLiteral("xterm")}},

        {QStringLiteral("custom"), QStringLiteral("Custom"),
         QStringLiteral("application-x-executable"), QStringLiteral("noop"),
         {}},
    };
}

bool MenuConfig::loadFromGroup(QSettings &ini, const QString &groupName)
{
    ini.beginGroup(groupName);

    // If the group is effectively empty, treat as "not present".
    const int count = ini.value(QStringLiteral("count"), 0).toInt();
    if (count <= 0 && ini.childKeys().isEmpty()
        && ini.childGroups().isEmpty()) {
        ini.endGroup();
        return false;
    }

    // Center: defaults to auto-detected task manager so the contract
    // (center == task manager) holds even if config omits the center.
    const QStringList defaultTaskMgr = detectTaskManager();
    const QString centerCmd =
        ini.value(QStringLiteral("center/command")).toString();
    m_center = MenuItem{
        QStringLiteral("center"),
        ini.value(QStringLiteral("center/label"),
                  QStringLiteral("Task Manager")).toString(),
        ini.value(QStringLiteral("center/icon"),
                  QStringLiteral("utilities-system-monitor")).toString(),
        QStringLiteral("command"),
        centerCmd.isEmpty() ? defaultTaskMgr : splitCommand(centerCmd),
    };

    m_segments.clear();
    for (int i = 1; i <= count; ++i) {
        const QString p = QString::number(i) + QLatin1Char('/');
        const QString cmd = ini.value(p + QStringLiteral("command")).toString();
        MenuItem item{
            ini.value(p + QStringLiteral("id"),
                      QStringLiteral("slot%1").arg(i)).toString(),
            ini.value(p + QStringLiteral("label"),
                      QStringLiteral("Slot %1").arg(i)).toString(),
            ini.value(p + QStringLiteral("icon"),
                      QStringLiteral("application-x-executable")).toString(),
            cmd.isEmpty() ? QStringLiteral("noop") : QStringLiteral("command"),
            splitCommand(cmd),
        };
        m_segments.push_back(item);
    }
    ini.endGroup();

    if (m_segments.isEmpty()) {
        // Config had a center but no segments: keep the default ring so the
        // menu is still useful.
        const MenuItem keepCenter = m_center;
        loadBuiltinDefault();
        m_center = keepCenter;
    }
    return true;
}

void MenuConfig::loadFromIniOrDefault()
{
    const QString path = configPath();
    if (!QFileInfo::exists(path)) {
        loadBuiltinDefault();
        return;
    }

    QSettings ini(path, QSettings::IniFormat);

    // A non-"default" menu id selects [radial:<id>] first; "default" (or a
    // missing per-id section) falls back to [radial], then the built-in default.
    if (!m_menuId.isEmpty() && m_menuId != QLatin1String("default")) {
        const QString idGroup =
            QStringLiteral("radial:") + m_menuId;
        if (loadFromGroup(ini, idGroup)) {
            return;
        }
    }

    if (loadFromGroup(ini, QStringLiteral("radial"))) {
        return;
    }

    loadBuiltinDefault();
}

} // namespace mx4
