#!/usr/bin/env bash
# uninstall.sh — remove the MX Master 4 desktop addon for the current user.
# Reverses install.sh. INIT-AGNOSTIC: stops the daemon via systemd when a user
# manager is present, and always SIGTERMs any ad-hoc daemon so the diverted
# Actions Ring panel is restored before anything is removed. Idempotent and
# non-destructive (never rm -rf's a user dir, only the files it owns).
#
# Preserves your config by default. Pass --purge to also delete
# ~/.config/mx4desktop/.
#
# Flags:
#   --purge      also delete ~/.config/mx4desktop/
#   --no-udev    skip the sudo udev removal (e.g. CI / throwaway install)
#   --prefix DIR uninstall from DIR instead of ~/.local (must match install)
set -euo pipefail

PURGE=0
DO_UDEV=1
PREFIX=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)    PURGE=1 ;;
        --no-udev)  DO_UDEV=0 ;;
        --prefix)   PREFIX="${2:?--prefix needs a directory}"; shift ;;
        --prefix=*) PREFIX="${1#--prefix=}" ;;
        -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "error: unknown argument '$1' (try --help)" >&2; exit 2 ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-${HOME}/.local}"
BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/mx4desktop"
DATA_DIR="${PREFIX}/share/mx4desktop"
APPS_DIR="${PREFIX}/share/applications"

XDG_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}"
UNIT_DIR="${XDG_CONFIG}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG}/autostart"
CONFIG_DIR="${XDG_CONFIG}/mx4desktop"
UDEV_RULE_DST="/etc/udev/rules.d/70-mx-master-4.rules"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# Same init probe as install.sh: systemd user manager only if it really works.
HAVE_SYSTEMD_USER=0
if command -v systemctl >/dev/null 2>&1 \
   && systemctl --user show-environment >/dev/null 2>&1; then
    HAVE_SYSTEMD_USER=1
fi

# Same desktop probe as install.sh: the KWin script is only ever installed on
# Plasma, so we only bother kpackagetool6 there (avoids a pointless query on
# non-Plasma boxes that merely happen to have the KDE tooling installed).
IS_PLASMA=0
case ":${XDG_CURRENT_DESKTOP:-}:" in
    *:KDE:*|*:plasma:*|*:Plasma:*) IS_PLASMA=1 ;;
esac

# --- 1. stop the daemon (graceful: restores the diverted panel) -------------
step "Stopping the daemon (graceful — restores the Actions Ring panel)"
if [[ "${HAVE_SYSTEMD_USER}" -eq 1 ]]; then
    # Stop first so the daemon's SIGTERM handler un-diverts the panel, then
    # disable so a leftover symlink can't auto-start a removed binary.
    systemctl --user stop mx4-overlay.service mx4desktop.service 2>/dev/null || true
    systemctl --user disable mx4-overlay.service mx4desktop.service 2>/dev/null || true
fi
# Always also SIGTERM an ad-hoc daemon (the only path on non-systemd inits, and
# a belt-and-braces on systemd). Patterns are anchored on the actual invocations
# ("-m mx4d" / a path ending in "/mx4-radial") so an unrelated process whose
# argv merely contains "mx4d" (e.g. an editor open on an "mx4desktop" file) is
# never hit.
if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -f '(^|[ /])python[0-9.]* -m mx4d($|[ ])' 2>/dev/null || true
    pkill -TERM -f '[ /]mx4-radial($|[ ])' 2>/dev/null || true
fi

# --- 2. remove installed files ----------------------------------------------
step "Removing installed files"
DESKTOP_FILE="${APPS_DIR}/mx4-config.desktop"
AUTOSTART_TEMPLATE="${DATA_DIR}/autostart/mx4desktop.desktop"
AUTOSTART_ENABLED="${AUTOSTART_DIR}/mx4desktop.desktop"

# Remove a file (or dir) only if present, and log only then, so the output is
# an honest list of what actually went away.
# Note the trailing `:` — without it the function's exit status is that of the
# final `[[ -e ]]` test, which is non-zero when the last path is already gone,
# and under `set -e` that would abort the script on a second (idempotent) run.
rm_if() { local p; for p in "$@"; do [[ -e "$p" ]] && { rm -rf "$p" && log "removed $p"; }; done; :; }
rm_if "${BIN_DIR}/mx4-radial" "${BIN_DIR}/mx4-config" "${BIN_DIR}/mx4d" \
      "${DESKTOP_FILE}" "${LIB_DIR}" "${AUTOSTART_TEMPLATE}"
# Only remove an enabled autostart entry if it is OURS (Exec runs mx4d), so a
# hand-rolled user entry is never clobbered.
if [[ -f "${AUTOSTART_ENABLED}" ]] && grep -qE '^Exec=.*mx4d( |$)' "${AUTOSTART_ENABLED}"; then
    rm -f "${AUTOSTART_ENABLED}" && log "removed ${AUTOSTART_ENABLED}"
fi
# Clean up our (now-empty) data subdir; rmdir is a no-op if non-empty.
rmdir "${DATA_DIR}/autostart" "${DATA_DIR}" 2>/dev/null || true

# systemd user units (only report ones that actually existed).
for unit in mx4desktop.service mx4-overlay.service; do
    if [[ -f "${UNIT_DIR}/${unit}" ]]; then
        rm -f "${UNIT_DIR}/${unit}" && log "removed ${UNIT_DIR}/${unit}"
    fi
done
if [[ "${HAVE_SYSTEMD_USER}" -eq 1 ]]; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

# --- 2b. KWin focus-bridge script -------------------------------------------
# install.sh installs (but never enables) the mx4-focus-bridge KWin script, and
# only on Plasma. Remove it best-effort wherever kpackagetool6 exists; we never
# touched kwinrc (install never enabled it), so there is nothing to un-set.
step "Removing KWin focus-bridge script"
if [[ "${IS_PLASMA}" -ne 1 ]]; then
    log "skipped: desktop is '${XDG_CURRENT_DESKTOP:-unknown}', not Plasma (never installed here)."
elif command -v kpackagetool6 >/dev/null 2>&1; then
    if kpackagetool6 --type KWin/Script --list 2>/dev/null | grep -q '^mx4-focus-bridge$'; then
        kpackagetool6 --type KWin/Script --remove mx4-focus-bridge 2>/dev/null \
            && log "removed KWin script 'mx4-focus-bridge'" \
            || log "could not remove KWin script 'mx4-focus-bridge' (non-fatal)"
    else
        log "KWin script 'mx4-focus-bridge' not installed"
    fi
else
    log "kpackagetool6 not found; nothing to remove"
fi

# --- 3. udev rule (needs sudo) ----------------------------------------------
step "Removing udev rule"
if [[ "${DO_UDEV}" -eq 0 ]]; then
    log "skipped (--no-udev). Remove it later with: sudo rm -f '${UDEV_RULE_DST}'"
elif [[ -f "${UDEV_RULE_DST}" ]]; then
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
