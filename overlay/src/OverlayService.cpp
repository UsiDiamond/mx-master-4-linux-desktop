#include "OverlayService.h"

#include <QLoggingCategory>

Q_LOGGING_CATEGORY(lcService, "mx4.service")

namespace mx4 {

OverlayService::OverlayService(QObject *parent)
    : QObject(parent)
{
}

const char *OverlayService::busName()
{
    // The overlay owns its OWN well-known name, distinct from the daemon's
    // dev.usidiamond.mx4 (which the daemon owns and the overlay only *calls*
    // for haptics). This lets both processes co-run: the daemon addresses the
    // overlay's object via this name to drive Show()/Hide()/ActionChosen.
    return "dev.usidiamond.mx4.Overlay";
}

const char *OverlayService::objectPath()
{
    return "/dev/usidiamond/mx4/Overlay";
}

const char *OverlayService::interfaceName()
{
    return "dev.usidiamond.mx4.Overlay";
}

void OverlayService::Show(const QString &menuId)
{
    qCInfo(lcService) << "D-Bus Show(" << menuId << ")";
    emit showRequested(menuId);
}

void OverlayService::Hide()
{
    qCInfo(lcService) << "D-Bus Hide()";
    emit hideRequested();
}

void OverlayService::ShowMedia()
{
    qCInfo(lcService) << "D-Bus ShowMedia()";
    emit showMediaRequested();
}

bool OverlayService::Commit(const QString &actionId)
{
    qCInfo(lcService) << "D-Bus Commit(" << actionId << ")";
    // Synchronous handler call: the app ensures a view exists then drives the
    // controller's commit path, returning success for the D-Bus reply.
    return m_commitHandler ? m_commitHandler(actionId) : false;
}

bool OverlayService::Activate(int index)
{
    qCInfo(lcService) << "D-Bus Activate(" << index << ")";
    return m_activateHandler ? m_activateHandler(index) : false;
}

} // namespace mx4
