#include "RadialController.h"

#include "DaemonHaptics.h"

#include <QLoggingCategory>
#include <QProcess>
#include <QVariantMap>
#include <QtMath>

Q_LOGGING_CATEGORY(lcRadial, "mx4.radial")

namespace mx4 {

RadialController::RadialController(DaemonHaptics *haptics, QObject *parent)
    : QObject(parent)
    , m_haptics(haptics)
{
    MenuConfig defaultCfg;
    setMenu(defaultCfg);
}

void RadialController::setMenu(const MenuConfig &config)
{
    m_center = config.center();
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
    // Shared tail of every commit (user release or programmatic Commit/Activate):
    // confirm tick -> argv-safe launch -> ActionChosen -> dismiss.
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

} // namespace mx4
