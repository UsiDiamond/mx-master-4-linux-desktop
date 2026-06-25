#include "RadialController.h"

#include "DaemonHaptics.h"

#include <QLoggingCategory>
#include <QProcess>
#include <QVariantMap>
#include <QtMath>

Q_LOGGING_CATEGORY(lcRadial, "mx4.radial")

namespace mx4 {

namespace {
// Below this net-slide magnitude (raw sensor units) a flick has no clear
// direction yet, so the center hub stays the target — sliding back toward the
// origin before releasing therefore cancels the pick. The daemon only begins a
// flick well past this, so in practice a segment is highlighted almost at once.
constexpr qreal kFlickMinMag = 120.0;
} // namespace

RadialController::RadialController(DaemonHaptics *haptics, QObject *parent)
    : QObject(parent)
    , m_haptics(haptics)
{
    MenuConfig defaultCfg;
    setMenu(defaultCfg);
}

void RadialController::setMenu(const MenuConfig &config)
{
    // Root entry (a fresh Show): reset the nav stack so Back can never escape
    // above the menu we were asked to show.
    m_menuStack.clear();
    m_currentMenuId = config.menuId();
    if (m_flickMode) {
        // A fresh mouse-driven show clears any stale flick state (beginFlick()
        // re-arms it for a flick show, which runs right after this).
        m_flickMode = false;
        emit flickModeChanged();
    }
    applyMenu(config, /*asSubmenu=*/false);
}

void RadialController::applyMenu(const MenuConfig &config, bool asSubmenu)
{
    // In a sub-ring the center hub becomes "Back" (return to the parent); at
    // the root it is the configured center action.
    m_center = asSubmenu
        ? MenuItem{QStringLiteral("back"), QStringLiteral("Back"),
                   QStringLiteral("go-previous"), QStringLiteral("back"),
                   {}, {}}
        : config.center();
    m_items = config.segments();

    m_segments.clear();
    m_segments.reserve(m_items.size());
    for (const MenuItem &item : m_items) {
        QVariantMap m;
        m.insert(QStringLiteral("id"), item.id);
        m.insert(QStringLiteral("label"), item.label);
        m.insert(QStringLiteral("icon"), item.iconName);
        m_segments.push_back(m);
    }

    m_highlightedIndex = -1;
    m_pointerEngaged = false;
    emit menuChanged();
    emit highlightChanged();
}

void RadialController::enterSubmenu(const QString &submenuId)
{
    if (submenuId.isEmpty()) {
        return;
    }
    qCInfo(lcRadial) << "enter submenu" << submenuId
                     << "from" << m_currentMenuId;
    m_menuStack.push_back(m_currentMenuId);
    m_currentMenuId = submenuId;
    if (m_haptics) {
        m_haptics->tick(); // a light nav tick, not the commit confirm buzz
    }
    applyMenu(MenuConfig(submenuId), /*asSubmenu=*/true);
}

void RadialController::goBack()
{
    if (m_menuStack.isEmpty()) {
        // Already at the root: a Back with nowhere to go just dismisses.
        cancel();
        return;
    }
    const QString parentId = m_menuStack.takeLast();
    qCInfo(lcRadial) << "back to" << parentId;
    m_currentMenuId = parentId;
    if (m_haptics) {
        m_haptics->tick();
    }
    applyMenu(MenuConfig(parentId), /*asSubmenu=*/!m_menuStack.isEmpty());
}

void RadialController::setHighlightedIndex(int idx)
{
    if (idx == m_highlightedIndex) {
        return;
    }
    m_highlightedIndex = idx;
    // Tick the motor on every *change* of highlighted segment (debounced in
    // DaemonHaptics). No-op when the daemon is absent.
    if (idx >= 0 && m_haptics) {
        m_haptics->tick();
    }
    emit highlightChanged();
}

void RadialController::highlightFromAngle(qreal deg, qreal radius, qreal deadZone)
{
    m_pointerEngaged = true;
    const int n = m_items.size();
    if (n == 0) {
        setHighlightedIndex(-1);
        return;
    }

    // Inside the dead-zone the center hub is the target (no segment).
    if (radius >= 0.0 && radius < deadZone) {
        setHighlightedIndex(-1);
        emit highlightChanged(); // refresh centerHighlighted
        return;
    }

    // Segments are centered on evenly spaced angles starting at 12 o'clock
    // (0 deg). Map the pointer angle to the nearest segment center.
    qreal a = std::fmod(deg, 360.0);
    if (a < 0.0) {
        a += 360.0;
    }
    const qreal step = 360.0 / n;
    int idx = static_cast<int>(std::lround(a / step)) % n;
    setHighlightedIndex(idx);
}

void RadialController::highlightNext()
{
    m_pointerEngaged = true;
    const int n = m_items.size();
    if (n == 0) {
        return;
    }
    const int next = (m_highlightedIndex < 0) ? 0
                                              : (m_highlightedIndex + 1) % n;
    setHighlightedIndex(next);
}

void RadialController::highlightPrev()
{
    m_pointerEngaged = true;
    const int n = m_items.size();
    if (n == 0) {
        return;
    }
    const int prev = (m_highlightedIndex <= 0) ? (n - 1)
                                               : (m_highlightedIndex - 1);
    setHighlightedIndex(prev);
}

void RadialController::launch(const MenuItem &item)
{
    if (item.actionType == QLatin1String("noop") || item.argv.isEmpty()) {
        qCDebug(lcRadial) << "no-op action" << item.id;
        return;
    }
    // SECURITY: argv launch only. No shell, no string interpolation, so menu
    // labels/commands can never inject. argv[0] is the program; the rest are
    // literal arguments.
    const QString program = item.argv.first();
    const QStringList args = item.argv.mid(1);
    qCInfo(lcRadial) << "launching" << item.id << program << args;
    const bool ok = QProcess::startDetached(program, args);
    if (!ok) {
        qCWarning(lcRadial) << "failed to start" << program
                            << "(not on PATH?) for action" << item.id;
    }
}

void RadialController::commit()
{
    const MenuItem chosen =
        (m_highlightedIndex >= 0 && m_highlightedIndex < m_items.size())
            ? m_items.at(m_highlightedIndex)
            : m_center; // press-release with no movement -> center action
    commitItem(chosen);
}

void RadialController::commitItem(const MenuItem &item)
{
    // Navigation actions stay in the overlay (no dismiss, no ActionChosen):
    // "submenu" drills into a nested ring, "back" returns to the parent.
    if (item.actionType == QLatin1String("submenu")) {
        enterSubmenu(item.submenuId);
        return;
    }
    if (item.actionType == QLatin1String("back")) {
        goBack();
        return;
    }
    // Terminal actions: confirm tick -> argv-safe launch -> ActionChosen ->
    // dismiss. A "noop" still confirms+dismisses (an intentional empty pick).
    if (m_haptics) {
        m_haptics->confirm();
    }
    launch(item);
    emit actionChosen(item.id);
    emit dismissRequested();
}

bool RadialController::commitByIndex(int index)
{
    if (index < 0) {
        // -1 (or any negative) means the center hub action.
        commitItem(m_center);
        return true;
    }
    if (index >= m_items.size()) {
        qCWarning(lcRadial) << "commitByIndex out of range" << index
                            << "of" << m_items.size();
        return false;
    }
    commitItem(m_items.at(index));
    return true;
}

bool RadialController::commitById(const QString &actionId)
{
    if (actionId.isEmpty() || actionId == m_center.id
        || actionId == QLatin1String("center")) {
        commitItem(m_center);
        return true;
    }
    for (const MenuItem &item : m_items) {
        if (item.id == actionId) {
            commitItem(item);
            return true;
        }
    }
    qCWarning(lcRadial) << "commitById: no segment with id" << actionId;
    return false;
}

void RadialController::cancel()
{
    if (m_haptics) {
        m_haptics->cancelBuzz();
    }
    qCDebug(lcRadial) << "cancelled";
    emit dismissRequested();
}

// -- flick (thumb-slide) steering ---------------------------------------
void RadialController::beginFlick()
{
    if (!m_flickMode) {
        m_flickMode = true;
        emit flickModeChanged();
    }
    // Engage the center as the "no direction yet" target until the first
    // vector lands; haptic ticks then fire as the highlight crosses segments.
    m_pointerEngaged = true;
    setHighlightedIndex(-1);
    emit highlightChanged();
    qCInfo(lcRadial) << "flick mode armed";
}

void RadialController::setFlickVector(int dx, int dy)
{
    m_pointerEngaged = true;
    const int n = m_items.size();
    if (n == 0) {
        setHighlightedIndex(-1);
        emit highlightChanged();
        return;
    }
    // Too little net movement -> no direction yet (center stays the target).
    const qreal mag = std::hypot(static_cast<qreal>(dx), static_cast<qreal>(dy));
    if (mag < kFlickMinMag) {
        setHighlightedIndex(-1);
        emit highlightChanged();
        return;
    }
    // Same angle convention as the pointer path: degrees clockwise from 12
    // o'clock. Sensor +x is rightward and +y is "down" (matching screen Y), so
    // atan2(dx, -dy) lands an upward slide on the top segment.
    qreal deg = qRadiansToDegrees(std::atan2(static_cast<qreal>(dx),
                                             static_cast<qreal>(-dy)));
    qreal a = std::fmod(deg, 360.0);
    if (a < 0.0) {
        a += 360.0;
    }
    const qreal step = 360.0 / n;
    const int idx = static_cast<int>(std::lround(a / step)) % n;
    setHighlightedIndex(idx);
}

void RadialController::commitFlick()
{
    if (m_highlightedIndex >= 0 && m_highlightedIndex < m_items.size()) {
        qCInfo(lcRadial) << "flick commit -> segment" << m_highlightedIndex;
        commitItem(m_items.at(m_highlightedIndex));
    } else {
        // Released without a clear direction: dismiss without acting.
        qCInfo(lcRadial) << "flick released with no direction -> cancel";
        cancel();
    }
}

} // namespace mx4
