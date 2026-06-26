// mx4 focus bridge — a KWin script that forwards window-activation changes to
// the mx4 daemon over D-Bus, so application-focus haptics work for native
// Wayland clients (which never touch X11 _NET_ACTIVE_WINDOW that the daemon's
// portable focus source watches).
//
// It calls:
//   bus name : dev.usidiamond.mx4
//   object   : /dev/usidiamond/mx4
//   interface: dev.usidiamond.mx4.Daemon
//   method   : FocusChanged(s appName) -> b
//
// callDBus is fire-and-forget from the script's perspective; if the daemon is
// not running the call simply fails silently — the desktop is never affected.
// EnabledByDefault is false (see metadata.json); the user opts in explicitly.

"use strict";

function appNameFor(client) {
    if (!client) {
        return "";
    }
    // resourceClass is the stable app id (e.g. "firefox"); caption is the
    // window title fallback. Guard every access — KWin hands us nulls at times.
    var name = client.resourceClass ? String(client.resourceClass) : "";
    if (!name && client.caption) {
        name = String(client.caption);
    }
    return name;
}

function onActivated(client) {
    var name = appNameFor(client);
    // Forward to the daemon. Last arg is an (optional) reply callback; we ignore
    // the boolean result — this is a fire-and-forget notification.
    callDBus(
        "dev.usidiamond.mx4",
        "/dev/usidiamond/mx4",
        "dev.usidiamond.mx4.Daemon",
        "FocusChanged",
        name,
        function (ok) { /* no-op: best-effort */ }
    );
}

// KWin's workspace activation signal differs slightly across versions:
//   * Plasma 6:        workspace.windowActivated(window)
//   * Plasma 5 legacy: workspace.clientActivated(client)
// Connect whichever exists so the script is portable across KWin versions.
if (typeof workspace !== "undefined") {
    if (workspace.windowActivated) {
        workspace.windowActivated.connect(onActivated);
    } else if (workspace.clientActivated) {
        workspace.clientActivated.connect(onActivated);
    }
}
