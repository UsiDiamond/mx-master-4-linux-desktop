#ifndef MX4_RADIALCONTROLLER_H
#define MX4_RADIALCONTROLLER_H

#include <QObject>
#include <QString>
#include <QVariantList>

#include "MenuConfig.h"

namespace mx4 {

class DaemonHaptics;

/**
 * The QML-facing brain of the radial menu. Exposes the menu model, the
 * highlighted index (driven by pointer angle and/or keyboard), and the
 * verbs the QML drives: highlightFromAngle(), commit(), cancel().
 *
 * Ownership: parented into the QObject tree; the DaemonHaptics it uses is
 * injected and owned by the caller (not deleted here).
 */
class RadialController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QVariantList segments READ segments NOTIFY menuChanged)
    Q_PROPERTY(QString centerLabel READ centerLabel NOTIFY menuChanged)
    Q_PROPERTY(QString centerIcon READ centerIcon NOTIFY menuChanged)
    Q_PROPERTY(int highlightedIndex READ highlightedIndex NOTIFY highlightChanged)
    Q_PROPERTY(bool centerHighlighted READ centerHighlighted NOTIFY highlightChanged)
    // True while the ring is being steered by a thumb-slide (flick) rather than
    // the mouse pointer; QML uses it to show a "slide to pick" affordance.
    Q_PROPERTY(bool flickMode READ flickMode NOTIFY flickModeChanged)

public:
    explicit RadialController(DaemonHaptics *haptics, QObject *parent = nullptr);

    // Replace the active menu (e.g. on Show(menuId)).
    void setMenu(const MenuConfig &config);

    QVariantList segments() const { return m_segments; }
    QString centerLabel() const { return m_center.label; }
    QString centerIcon() const { return m_center.iconName; }
    int highlightedIndex() const { return m_highlightedIndex; }
    bool centerHighlighted() const { return m_highlightedIndex < 0 && m_pointerEngaged; }
    bool flickMode() const { return m_flickMode; }

public slots:
    // deg measured clockwise from 12 o'clock (0..360). Inside the dead-zone
    // radius the QML passes a negative radius to keep the center hub active.
    void highlightFromAngle(qreal deg, qreal radius, qreal deadZone);

    // Keyboard navigation (arrow keys / tab).
    void highlightNext();
    void highlightPrev();

    // Commit the current highlight (release / Enter). If nothing is
    // highlighted (a press-release with no movement) the CENTER action runs.
    void commit();

    // Programmatic commit (D-Bus Overlay.Commit / .Activate). Drives the SAME
    // commit()/launch path as a user release, so the full show->commit->launch
    // chain is automatable on Wayland without a physical tap.
    //   commitByIndex(-1)         -> the center action
    //   commitByIndex(0..n-1)     -> that segment
    //   commitById("<id>")        -> the segment (or center) with that id
    // Returns whether a matching item was found and committed.
    bool commitByIndex(int index);
    bool commitById(const QString &actionId);

    // Dismiss without acting (Escape / outside click).
    void cancel();

    // Flick (thumb-slide) steering, driven by the daemon over D-Bus:
    //   beginFlick()            enter flick mode (no mouse pick; highlight by dir)
    //   setFlickVector(dx, dy)  highlight the segment at that slide direction
    //   commitFlick()           activate the highlighted segment, else cancel
    void beginFlick();
    void setFlickVector(int dx, int dy);
    void commitFlick();

signals:
    void menuChanged();
    void highlightChanged();
    void flickModeChanged();
    // Emitted on commit with the chosen item id; main wires this to the D-Bus
    // Overlay.ActionChosen signal and to window dismissal.
    void actionChosen(const QString &actionId);
    // Asks the window/app to hide & quit-or-idle.
    void dismissRequested();

private:
    void setHighlightedIndex(int idx);
    void launch(const MenuItem &item);
    // Shared commit tail: launch/navigate per item.actionType. command/noop
    // launch + dismiss; "submenu" drills in; "back" returns to the parent.
    void commitItem(const MenuItem &item);
    // Swap the live menu to `config`. asSubmenu replaces the center hub with a
    // "Back" item so any sub-ring can return to its parent.
    void applyMenu(const MenuConfig &config, bool asSubmenu);
    // Drill into / return from a nested menu (no dismiss).
    void enterSubmenu(const QString &submenuId);
    void goBack();

    DaemonHaptics *m_haptics; // not owned
    MenuItem m_center;
    QVector<MenuItem> m_items;
    QVariantList m_segments;   // QML-friendly mirror of m_items
    int m_highlightedIndex = -1;
    bool m_pointerEngaged = false;
    bool m_flickMode = false;       // steered by thumb-slide, not the pointer
    QString m_currentMenuId;        // id of the menu currently shown
    QStringList m_menuStack;        // ancestor menu ids (empty at the root)
};

} // namespace mx4

#endif // MX4_RADIALCONTROLLER_H
