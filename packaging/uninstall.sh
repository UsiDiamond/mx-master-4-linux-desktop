#!/usr/bin/env bash
# uninstall.sh — remove the MX Master 4 desktop addon for the current user.
# Reverses install.sh. Idempotent. Leaves the mouse CLEAN: it stops the daemon
# gracefully first (the daemon's SIGTERM handler restores the diverted Actions
# Ring panel to non-diverted) before removing anything.
#
# Preserves your config by default. Pass --purge to also delete
# ~/.config/mx4desktop/.
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib/mx4desktop"
UNIT_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/mx4desktop"
UDEV_RULE_DST="/etc/udev/rules.d/70-mx-master-4.rules"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# --- 1. stop + disable services (graceful: restores the diverted panel) ------
step "Stopping services (graceful — restores the Actions Ring panel)"
if command -v systemctl >/dev/null 2>&1; then
    # Stop first so the daemon's SIGTERM handler un-diverts the panel, then
    # disable so a leftover symlink can't auto-start a removed binary.
    systemctl --user stop mx4-overlay.service mx4desktop.service 2>/dev/null || true
    systemctl --user disable mx4-overlay.service mx4desktop.service 2>/dev/null || true
fi
# Belt-and-braces: if the daemon was started ad hoc (not via systemd), SIGTERM
# it too so it restores the panel before we delete its launcher. The patterns
# are anchored on the actual invocations ("-m mx4d" / a path ending in
# "/mx4-radial") so an unrelated process whose argv merely contains the
# substring "mx4d" (e.g. an editor open on an "mx4desktop" file) is never hit.
if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -f '(^|[ /])python[0-9.]* -m mx4d($|[ ])' 2>/dev/null || true
    pkill -TERM -f '[ /]mx4-radial($|[ ])' 2>/dev/null || true
fi

# --- 2. remove installed files ----------------------------------------------
step "Removing installed files"
DESKTOP_FILE="${HOME}/.local/share/applications/mx4-config.desktop"
rm -f  "${BIN_DIR}/mx4-radial"          && log "removed ${BIN_DIR}/mx4-radial"
rm -f  "${BIN_DIR}/mx4-config"          && log "removed ${BIN_DIR}/mx4-config"
rm -f  "${BIN_DIR}/mx4d"                && log "removed ${BIN_DIR}/mx4d"
rm -f  "${DESKTOP_FILE}"                && log "removed ${DESKTOP_FILE}"
rm -rf "${LIB_DIR}"                     && log "removed ${LIB_DIR}"
rm -f  "${UNIT_DIR}/mx4desktop.service" && log "removed ${UNIT_DIR}/mx4desktop.service"
rm -f  "${UNIT_DIR}/mx4-overlay.service" && log "removed ${UNIT_DIR}/mx4-overlay.service"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

# --- 2b. KWin focus-bridge script -------------------------------------------
# install.sh installs (but never enables) the mx4-focus-bridge KWin script.
# Remove it here best-effort. We never touched kwinrc (install never enabled
# it), so there is nothing to un-set there.
step "Removing KWin focus-bridge script"
if command -v kpackagetool6 >/dev/null 2>&1; then
    if kpackagetool6 --type KWin/Script --list 2>/dev/null | grep -q '^mx4-focus-bridge$'; then
        kpackagetool6 --type KWin/Script --remove mx4-focus-bridge 2>/dev/null \
            && log "removed KWin script 'mx4-focus-bridge'" \
            || log "could not remove KWin script 'mx4-focus-bridge' (non-fatal)"
    else
        log "KWin script 'mx4-focus-bridge' not installed"
    fi
else
    log "kpackagetool6 not found; skipping KWin script removal"
fi

# --- 3. udev rule (needs sudo) ----------------------------------------------
step "Removing udev rule (needs sudo)"
if [[ -f "${UDEV_RULE_DST}" ]]; then
    log "removing ${UDEV_RULE_DST} (you may be prompted for your password)"
    sudo rm -f "${UDEV_RULE_DST}"
    sudo udevadm control --reload 2>/dev/null || true
    log "udev rule removed + reloaded"
else
    log "no udev rule installed"
fi

# --- 4. config -------------------------------------------------------------
step "Config"
if [[ "${PURGE}" -eq 1 ]]; then
    rm -rf "${CONFIG_DIR}" && log "purged ${CONFIG_DIR}"
else
    log "kept ${CONFIG_DIR} (pass --purge to delete it)"
fi

step "Done. The MX Master 4 is left in its native (non-diverted) state."
