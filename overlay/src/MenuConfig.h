#ifndef MX4_MENUCONFIG_H
#define MX4_MENUCONFIG_H

#include <QObject>
#include <QString>
#include <QStringList>
#include <QVector>

class QSettings;

namespace mx4 {

/**
 * One radial slot (or the center hub). actionType selects how the item acts:
 *   "command" -> launch argv with QProcess (no shell, injection-free);
 *   "submenu" -> open the nested menu named submenuId (drill down a ring);
 *   "back"    -> return to the parent menu (the center of any sub-ring);
 *   "noop"    -> do nothing (an empty/placeholder slot).
 */
struct MenuItem
{
    QString id;             // stable identifier, e.g. "taskmanager"
    QString label;          // human label shown under the segment
    QString iconName;       // freedesktop theme icon name
    QString actionType;     // "command" | "submenu" | "back" | "noop"
    QStringList argv;       // launch argument vector (argv[0] = program)
    QString submenuId;      // for actionType=="submenu": the menu id to open
};

/**
 * Loads the radial menu definition. Reads ~/.config/mx4desktop/config.ini
 * [radial] when present, otherwise yields a sensible built-in default whose
 * CENTER action is the auto-detected task manager / system monitor.
 *
 * Config schema (INI), all keys optional:
 *   [radial]
 *   center/label=Task Manager
 *   center/icon=utilities-system-monitor
 *   center/command=plasma-systemmonitor
 *   count=6
 *   1/id=launcher
 *   1/label=Launcher
 *   1/icon=system-run
 *   1/command=krunner
 *   ...
 * "command" is split with QProcess::splitCommand (quote-aware, NO shell).
 *
 * Nested menus: a slot (or the center) may open another ring instead of
 * launching, via a "submenu" key naming another section's id:
 *   center/submenu=apps          ; center opens [radial:apps]
 *   6/submenu=apps-system        ; slot 6 opens [radial:apps-system]
 * A "submenu" key takes precedence over "command". The overlay shows a "Back"
 * hub at the center of any opened sub-ring, so no Back slot is needed.
 */
class MenuConfig
{
public:
    // menuId selects the config section: "default" -> [radial]; any other id
    // -> [radial:<id>], falling back to [radial] then the built-in default.
    explicit MenuConfig(const QString &menuId = QStringLiteral("default"));

    // The id this config was loaded for ("default", "apps", ...). Used by the
    // controller to track the nav stack when drilling into submenus.
    QString menuId() const { return m_menuId; }

    // The center hub action (default = task manager).
    const MenuItem &center() const { return m_center; }

    // The ring segments, in clockwise order starting at 12 o'clock.
    const QVector<MenuItem> &segments() const { return m_segments; }

    // Absolute path of the shared config file (may not exist).
    static QString configPath();

    // First-on-PATH task manager argv for this environment.
    static QStringList detectTaskManager();

private:
    // Returns true if a non-empty [groupName] section was loaded from ini.
    bool loadFromGroup(QSettings &ini, const QString &groupName);
    void loadFromIniOrDefault();
    void loadBuiltinDefault();

    QString m_menuId;
    MenuItem m_center;
    QVector<MenuItem> m_segments;
};

} // namespace mx4

#endif // MX4_MENUCONFIG_H
