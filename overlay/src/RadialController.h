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

public:
    explicit RadialController(DaemonHaptics *haptics, QObject *parent = nullptr);

    // Replace the active menu (e.g. on Show(menuId)).
    void setMenu(const MenuConfig &config);

    QVariantList segments() const { return m_segments; }
    QString centerLabel() const { return m_center.label; }
    QString centerIcon() const { return m_center.iconName; }
    int highlightedIndex() const { return m_highlightedIndex; }
    bool centerHighlighted() const { return m_highlightedIndex < 0 && m_pointerEngaged; }

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

    // Dismiss without acting (Escape / outside click).
    void cancel();

signals:
    void menuChanged();
    void highlightChanged();
    // Emitted on commit with the chosen item id; main wires this to the D-Bus
    // Overlay.ActionChosen signal and to window dismissal.
    void actionChosen(const QString &actionId);
    // Asks the window/app to hide & quit-or-idle.
    void dismissRequested();

private:
    void setHighlightedIndex(int idx);
    void launch(const MenuItem &item);

    DaemonHaptics *m_haptics; // not owned
    MenuItem m_center;
    QVector<MenuItem> m_items;
    QVariantList m_segments;   // QML-friendly mirror of m_items
    int m_highlightedIndex = -1;
    bool m_pointerEngaged = false;
};

} // namespace mx4

#endif // MX4_RADIALCONTROLLER_H
