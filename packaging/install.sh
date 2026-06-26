#!/usr/bin/env bash
# install.sh — install the MX Master 4 Linux Desktop addon (daemon + overlay + config
# GUI) for the current user. INIT-AGNOSTIC and DE-AWARE:
#
#   * Init: detects whether `systemctl --user` actually works. On systemd it
#     ALSO installs the systemd user units and prints `systemctl --user`
#     commands; on OpenRC / runit / s6 / any non-systemd init it relies on the
#     portable XDG autostart entry and prints `mx4d &` / `pkill` guidance — it
#     never calls systemctl.
#   * Autostart: always installs a portable XDG autostart *template* (Type=
#     Application, Exec=mx4d). It is NOT enabled by default; pass
#     --enable-autostart (or copy it to ~/.config/autostart yourself) to enable.
#   * DE: the KWin focus-bridge is Plasma-Wayland-ONLY. It is installed only when
#     the desktop is Plasma; on LXQt/X11/anything else it is skipped (the
#     daemon's _NET_ACTIVE_WINDOW focus source is native there).
#
# Idempotent: safe to re-run; only ever creates/overwrites files it owns, never
# deletes user data, never overwrites an existing config, never enables anything
# unless you ask.
#
# What it installs (all under your home, except the one sudo udev step):
#   * overlay binary      -> ~/.local/bin/mx4-radial   (built with cmake)
#   * config GUI binary   -> ~/.local/bin/mx4-config   (built with cmake)
#   * config .desktop     -> ~/.local/share/applications/mx4-config.desktop
#   * daemon package      -> ~/.local/lib/mx4desktop/mx4d/   (copied source)
#   * daemon launcher     -> ~/.local/bin/mx4d   (system python, NO venv/pip)
#   * autostart template  -> ~/.local/share/mx4desktop/autostart/mx4desktop.desktop
#                            (+ ~/.config/autostart/ only with --enable-autostart)
#   * systemd user units   -> ~/.config/systemd/user/...  (ONLY if systemd-user)
#   * udev rule           -> /etc/udev/rules.d/70-mx-master-4.rules   (needs sudo)
#   * KWin script          -> user KWin scripts  (ONLY on Plasma; never enabled)
#   * default config      -> ~/.config/mx4desktop/config.ini   (only if absent)
#
# Flags:
#   --enable-autostart   also copy the autostart .desktop into ~/.config/autostart
#   --no-udev            skip the sudo udev step (e.g. CI / throwaway install)
#   --prefix DIR         install under DIR instead of ~/.local (testing)
set -euo pipefail

# --- args -------------------------------------------------------------------
ENABLE_AUTOSTART=0
DO_UDEV=1
PREFIX=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable-autostart) ENABLE_AUTOSTART=1 ;;
        --no-udev)          DO_UDEV=0 ;;
        --prefix)           PREFIX="${2:?--prefix needs a directory}"; shift ;;
        --prefix=*)         PREFIX="${1#--prefix=}" ;;
        -h|--help)
            sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "error: unknown argument '$1' (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# --- locate the repo (this script lives in packaging/) ----------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

OVERLAY_SRC="${REPO_DIR}/overlay"
OVERLAY_BUILD="${OVERLAY_SRC}/build"
CONFIG_SRC="${REPO_DIR}/config-ui"
CONFIG_BUILD="${CONFIG_SRC}/build"
KWIN_SRC="${REPO_DIR}/packaging/kwin"
DAEMON_SRC="${REPO_DIR}/daemon/mx4d"
AUTOSTART_SRC="${SCRIPT_DIR}/autostart/mx4desktop.desktop"

# Install roots. --prefix DIR puts bin/lib/share under DIR (for testing); the
# default is the per-user ~/.local. Config + autostart + units always live in
# the XDG config home so the apps and the session manager find them.
PREFIX="${PREFIX:-${HOME}/.local}"
BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/mx4desktop"
DATA_DIR="${PREFIX}/share/mx4desktop"
APPS_DIR="${PREFIX}/share/applications"
AUTOSTART_TEMPLATE="${DATA_DIR}/autostart/mx4desktop.desktop"

XDG_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}"
UNIT_DIR="${XDG_CONFIG}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG}/autostart"
CONFIG_DIR="${XDG_CONFIG}/mx4desktop"
CONFIG_FILE="${CONFIG_DIR}/config.ini"

UDEV_RULE_SRC="${SCRIPT_DIR}/udev/70-mx-master-4.rules"
UDEV_RULE_DST="/etc/udev/rules.d/70-mx-master-4.rules"

PYTHON_BIN="${MX4_PYTHON:-$(command -v python3 || command -v python || true)}"

log()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# --- init-system detection --------------------------------------------------
# The portable autostart is XDG (~/.config/autostart). systemd user units are a
# bonus ONLY when `systemctl --user` actually works. We require BOTH the binary
# and a working user manager (a live /run/systemd/private socket) — on this box
# /run/systemd can exist without systemd as PID 1 and with no systemctl, so we
# probe the real thing rather than just stat'ing a path.
HAVE_SYSTEMD_USER=0
if command -v systemctl >/dev/null 2>&1 \
   && systemctl --user show-environment >/dev/null 2>&1; then
    HAVE_SYSTEMD_USER=1
fi

# --- desktop detection (Plasma-only KWin script) ----------------------------
# XDG_CURRENT_DESKTOP is a colon list (e.g. "KDE", "LXQt", "KDE:plasma").
IS_PLASMA=0
case ":${XDG_CURRENT_DESKTOP:-}:" in
    *:KDE:*|*:plasma:*|*:Plasma:*) IS_PLASMA=1 ;;
esac

# --- preflight --------------------------------------------------------------
step "Preflight"
if [[ -z "${PYTHON_BIN}" ]]; then
    echo "error: no python3/python on PATH (set MX4_PYTHON=/path/to/python)" >&2
    exit 1
fi
log "python:  ${PYTHON_BIN} ($(${PYTHON_BIN} --version 2>&1))"
for tool in cmake; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "error: '${tool}' is required to build the overlay" >&2
        exit 1
    fi
done
if [[ "${HAVE_SYSTEMD_USER}" -eq 1 ]]; then
    log "init:    systemd (user manager available — will install user units)"
else
    log "init:    non-systemd (no working 'systemctl --user' — XDG autostart only)"
fi
if [[ "${IS_PLASMA}" -eq 1 ]]; then
    log "desktop: Plasma (XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-?}) — KWin bridge eligible"
else
    log "desktop: ${XDG_CURRENT_DESKTOP:-unknown} (not Plasma) — KWin focus bridge skipped"
fi

mkdir -p "${BIN_DIR}" "${LIB_DIR}" "${DATA_DIR}" "${APPS_DIR}" "${CONFIG_DIR}"

# --- 1. build + install the overlay binary ----------------------------------
step "Building the radial overlay (cmake)"
GEN_ARGS=()
if command -v ninja >/dev/null 2>&1; then
    GEN_ARGS=(-G Ninja)
fi
cmake -S "${OVERLAY_SRC}" -B "${OVERLAY_BUILD}" "${GEN_ARGS[@]}"
cmake --build "${OVERLAY_BUILD}"

OVERLAY_BIN="${OVERLAY_BUILD}/mx4-radial"
if [[ ! -x "${OVERLAY_BIN}" ]]; then
    echo "error: overlay build did not produce ${OVERLAY_BIN}" >&2
    exit 1
fi
install -Dm755 "${OVERLAY_BIN}" "${BIN_DIR}/mx4-radial"
log "installed ${BIN_DIR}/mx4-radial"

# --- 1b. build + install the config GUI -------------------------------------
step "Building the config GUI (cmake)"
cmake -S "${CONFIG_SRC}" -B "${CONFIG_BUILD}" "${GEN_ARGS[@]}"
cmake --build "${CONFIG_BUILD}"

CONFIG_BIN="${CONFIG_BUILD}/mx4-config"
if [[ ! -x "${CONFIG_BIN}" ]]; then
    echo "error: config GUI build did not produce ${CONFIG_BIN}" >&2
    exit 1
fi
install -Dm755 "${CONFIG_BIN}" "${BIN_DIR}/mx4-config"
log "installed ${BIN_DIR}/mx4-config"

# Desktop launcher so the settings window shows in the application menu.
DESKTOP_DST="${APPS_DIR}/mx4-config.desktop"
install -Dm644 "${CONFIG_SRC}/mx4-config.desktop" "${DESKTOP_DST}"
log "installed ${DESKTOP_DST}"

# mx4-show: a hotkey/button helper that opens the ring WITHOUT diverting any
# mouse button (bind it to a global shortcut in your DE). See docs/INSTALL.md.
install -Dm755 "${SCRIPT_DIR}/bin/mx4-show" "${BIN_DIR}/mx4-show"
log "installed ${BIN_DIR}/mx4-show"

# mx4-playpause: toggle play/pause on the active MPRIS player (browser video,
# music) without playerctl — for a radial "Play / Pause" segment or a hotkey.
install -Dm755 "${SCRIPT_DIR}/bin/mx4-playpause" "${BIN_DIR}/mx4-playpause"
log "installed ${BIN_DIR}/mx4-playpause"

# --- 2. install the daemon as a python package (NO venv, NO pip) -------------
step "Installing the daemon package"
# Replace the package tree atomically-ish: clear the old copy, copy fresh, so a
# renamed/removed module never lingers. We only ever touch our own LIB_DIR.
rm -rf "${LIB_DIR}/mx4d"
mkdir -p "${LIB_DIR}/mx4d"
( cd "${DAEMON_SRC}" && \
  find . -name '__pycache__' -prune -o -name '*.pyc' -prune -o -type f -print0 | \
  while IFS= read -r -d '' f; do
      install -Dm644 "${f}" "${LIB_DIR}/mx4d/${f}"
  done )
log "installed daemon package -> ${LIB_DIR}/mx4d"

# Launcher: runs the SYSTEM python with PYTHONPATH pointed at LIB_DIR so
# `python -m mx4d` resolves. No venv, no pip — matches the runtime constraint.
cat > "${BIN_DIR}/mx4d" <<EOF
#!/usr/bin/env bash
# mx4d launcher (generated by install.sh). Runs the daemon with the system
# python and no virtualenv: PYTHONPATH points at the installed package tree.
export PYTHONPATH="${LIB_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${PYTHON_BIN}" -m mx4d "\$@"
EOF
chmod 755 "${BIN_DIR}/mx4d"
log "installed ${BIN_DIR}/mx4d (system python: ${PYTHON_BIN})"

# Supervisor: keeps the daemon alive across MX4 sleep/wake and the boot-time
# race where the device is not ready at login (the daemon exits when the MX4 is
# absent; autostart fires only once). Autostart runs THIS, which relaunches the
# daemon with backoff. Installed verbatim from the repo.
install -Dm755 "${SCRIPT_DIR}/bin/mx4d-supervise" "${BIN_DIR}/mx4d-supervise"
log "installed ${BIN_DIR}/mx4d-supervise"

# --- 3. portable XDG autostart template (init-agnostic) ---------------------
step "Autostart (portable XDG entry)"
# Install the template into our data dir always. We rewrite Exec= to the
# absolute supervisor + absolute mx4d launcher so it works even when
# ~/.local/bin is not on the session PATH (common under display managers), and
# so a device-not-ready-at-login no longer leaves haptics dead until next login.
install -Dm644 "${AUTOSTART_SRC}" "${AUTOSTART_TEMPLATE}"
"${PYTHON_BIN}" - "${AUTOSTART_TEMPLATE}" "${BIN_DIR}/mx4d-supervise ${BIN_DIR}/mx4d" <<'PYEOF'
import sys
path, exec_path = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()
out = []
for ln in lines:
    if ln.startswith("Exec="):
        out.append(f"Exec={exec_path}\n")
    else:
        out.append(ln)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(out)
PYEOF
log "installed autostart template -> ${AUTOSTART_TEMPLATE}"

if [[ "${ENABLE_AUTOSTART}" -eq 1 ]]; then
    mkdir -p "${AUTOSTART_DIR}"
    install -Dm644 "${AUTOSTART_TEMPLATE}" "${AUTOSTART_DIR}/mx4desktop.desktop"
    log "ENABLED autostart -> ${AUTOSTART_DIR}/mx4desktop.desktop"
else
    log "autostart NOT enabled (pass --enable-autostart, or copy the template:"
    log "    cp '${AUTOSTART_TEMPLATE}' '${AUTOSTART_DIR}/mx4desktop.desktop')"
fi

# --- 3b. systemd user units (ONLY when systemd-user is available) -----------
if [[ "${HAVE_SYSTEMD_USER}" -eq 1 ]]; then
    step "Installing systemd user units"
    # The packaged units use %h/.local/bin/...; for a non-default --prefix the
    # ExecStart still resolves via the launcher on PATH, but for the default
    # ~/.local install these paths are exact. Copy verbatim.
    install -Dm644 "${SCRIPT_DIR}/systemd/mx4desktop.service" "${UNIT_DIR}/mx4desktop.service"
    install -Dm644 "${SCRIPT_DIR}/systemd/mx4-overlay.service" "${UNIT_DIR}/mx4-overlay.service"
    log "installed ${UNIT_DIR}/mx4desktop.service"
    log "installed ${UNIT_DIR}/mx4-overlay.service"
    systemctl --user daemon-reload || true
else
    step "systemd user units"
    log "skipped (no systemd user manager on this box — using XDG autostart)"
fi

# --- 4. default config (only if none exists) --------------------------------
step "Default config"
if [[ -e "${CONFIG_FILE}" ]]; then
    log "keeping existing ${CONFIG_FILE} (not overwritten)"
else
    # Let the daemon write its own fully-populated defaults (auto-detects the
    # task manager for this DE). PYTHONPATH so it imports the installed package.
    # PYTHONDONTWRITEBYTECODE keeps importing mx4d from leaving stray .pyc/
    # __pycache__ in the installed package tree.
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${LIB_DIR}${PYTHONPATH:+:$PYTHONPATH}" \
        "${PYTHON_BIN}" -c 'from mx4d.config import load_config; load_config()'
    log "wrote default ${CONFIG_FILE}"
fi
# Point the overlay command at the installed binary so the daemon's lazy launch
# finds it even if ~/.local/bin is not on the service PATH.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${LIB_DIR}${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON_BIN}" - "$CONFIG_FILE" "${BIN_DIR}/mx4-radial" <<'PYEOF'
import sys, configparser
path, overlay_bin = sys.argv[1], sys.argv[2]
p = configparser.ConfigParser()
p.read(path, encoding="utf-8")
if not p.has_section("overlay"):
    p.add_section("overlay")
# Only set if unset or still the bare default, so a user override is respected.
cur = p.get("overlay", "command", fallback="").strip()
if cur in ("", "mx4-radial"):
    p.set("overlay", "command", overlay_bin)
    with open(path, "w", encoding="utf-8") as fh:
        p.write(fh)
PYEOF
log "overlay command -> ${BIN_DIR}/mx4-radial"

# --- 5. udev rule (the one step that needs sudo) ----------------------------
step "udev rule"
if [[ "${DO_UDEV}" -eq 0 ]]; then
    log "skipped (--no-udev). Install it later with:"
    log "    sudo install -Dm644 '${UDEV_RULE_SRC}' '${UDEV_RULE_DST}'"
    log "    sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw"
elif [[ -f "${UDEV_RULE_DST}" ]] && cmp -s "${UDEV_RULE_SRC}" "${UDEV_RULE_DST}"; then
    log "udev rule already up to date at ${UDEV_RULE_DST}"
else
    log "installing ${UDEV_RULE_DST} (you may be prompted for your password)"
    sudo install -Dm644 "${UDEV_RULE_SRC}" "${UDEV_RULE_DST}"
    sudo udevadm control --reload || true
    sudo udevadm trigger --subsystem-match=hidraw || true
    log "udev rule installed + reloaded (re-plug the receiver if access is denied)"
fi

# --- 6. KWin focus-bridge script (Plasma-only, installed NOT enabled) -------
step "KWin focus-bridge script (Plasma-Wayland only)"
KWIN_ENABLE_HINT=""
if [[ "${IS_PLASMA}" -ne 1 ]]; then
    log "skipped: desktop is '${XDG_CURRENT_DESKTOP:-unknown}', not Plasma."
    log "on X11/LXQt the daemon's _NET_ACTIVE_WINDOW focus source is native + complete."
elif command -v kpackagetool6 >/dev/null 2>&1; then
    # Install (or upgrade) the package into the user's KWin scripts. We do NOT
    # enable it (no kwriteconfig6 / reconfigure) — it stays installed-but-inert
    # until the user opts in. EnabledByDefault=false reinforces this.
    if kpackagetool6 --type KWin/Script --list 2>/dev/null | grep -q '^mx4-focus-bridge$'; then
        kpackagetool6 --type KWin/Script --upgrade "${KWIN_SRC}" || \
            log "kpackagetool6 upgrade failed (non-fatal)"
        log "upgraded KWin script 'mx4-focus-bridge' (still NOT enabled)"
    else
        kpackagetool6 --type KWin/Script --install "${KWIN_SRC}" || \
            log "kpackagetool6 install failed (non-fatal)"
        log "installed KWin script 'mx4-focus-bridge' (NOT enabled)"
    fi
    KWIN_ENABLE_HINT=$'\nTo ENABLE the native-Wayland focus bridge (opt-in, Plasma-Wayland):\n    kwriteconfig6 --file kwinrc --group Plugins --key mx4-focus-bridgeEnabled true\n    qdbus6 org.kde.KWin /KWin reconfigure\n    # (or System Settings > Window Management > KWin Scripts)'
else
    log "Plasma detected but kpackagetool6 not found; skipping KWin focus-bridge."
fi

# --- done -------------------------------------------------------------------
# Print start/enable guidance tailored to the detected init.
START_GUIDE=""
if [[ "${HAVE_SYSTEMD_USER}" -eq 1 ]]; then
    START_GUIDE=$(cat <<EOF
To start NOW (this session only, nothing auto-enabled):
    systemctl --user start mx4desktop.service mx4-overlay.service
    # or run them ad hoc in a terminal:
    #   mx4d --verbose
    #   mx4-radial            # service mode (no --demo)

To ENABLE autostart on every login (opt-in):
    systemctl --user enable --now mx4desktop.service mx4-overlay.service
    # (the portable XDG autostart entry also works; --enable-autostart installs it)
EOF
)
else
    START_GUIDE=$(cat <<EOF
This box has no systemd user manager (OpenRC / runit / s6 / ...), so there are
NO 'systemctl --user' commands. Start the daemon directly:
    mx4d --verbose &          # daemon; it lazy-launches the overlay on demand
    # stop it again (gracefully restores the Actions Ring panel):
    pkill -TERM -f 'python.* -m mx4d'

To ENABLE autostart on every login (portable, no systemd):
    re-run with --enable-autostart, or copy the template:
    cp '${AUTOSTART_TEMPLATE}' '${AUTOSTART_DIR}/mx4desktop.desktop'
    # then mx4d starts at your next login; it lazy-launches the overlay.
EOF
)
fi

cat <<EOF

==> Done. Installed for user '$(id -un)'.

${START_GUIDE}

To EDIT settings (haptics, ambient sources, the radial menu):
    mx4-config            # or launch "MX Master 4 Settings" from the menu
${KWIN_ENABLE_HINT}

Config:    ${CONFIG_FILE}
Uninstall: ${SCRIPT_DIR}/uninstall.sh

If ${BIN_DIR} is not on your PATH, add it:
    export PATH="${BIN_DIR}:\$PATH"
EOF
