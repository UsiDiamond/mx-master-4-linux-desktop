#!/usr/bin/env bash
#
# Universal "install from git" bootstrap for mx-master-4-desktop.
#
# Clone the repo and run this on most Linux distros: it detects your package
# manager, installs the build + runtime dependencies, then builds and installs
# everything under ~/.local (with one sudo step for the udev rule).
#
#   git clone https://github.com/UsiDiamond/mx-master-4-desktop
#   cd mx-master-4-desktop
#   ./install.sh
#
# Flags:
#   --no-deps           skip dependency installation (you manage them yourself)
#   --dry-run           print the detected distro + dependency list, then exit
#   --enable-autostart  enable the daemon at login          (passed through)
#   --no-udev           skip the udev rule (e.g. in a container)  (passed through)
#   --prefix DIR        install prefix, default ~/.local    (passed through)
# Any other flags are passed through to packaging/install.sh.
#
# Package managers: apt (Debian/Ubuntu/Mint/Pop), dnf (Fedora/RHEL), pacman
# (Arch/Manjaro/EndeavourOS), zypper (openSUSE). Gentoo: prefer the ebuild in
# packaging/gentoo/. Anything else: install deps from docs/INSTALL.md, --no-deps.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY=0; WITH_DEPS=1; PASS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --no-deps) WITH_DEPS=0 ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) PASS+=("$1") ;;
    esac
    shift
done

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

PRETTY="unknown"
[ -r /etc/os-release ] && PRETTY="$(. /etc/os-release && echo "${PRETTY_NAME:-${ID:-unknown}}")"

PM=""
for m in apt-get dnf zypper pacman emerge; do
    have "$m" && { PM="$m"; break; }
done

# REQ = stable names that must install; OPT = version-variable names installed
# best-effort (a missing QML module / LayerShellQt only costs Wayland-overlay or
# a runtime QML module, never the build).
REQ=(); OPT=(); PM_UPDATE=":"; PM_INSTALL=""
case "$PM" in
    apt-get)
        # extra-cmake-modules is intentionally NOT installed on apt: on Ubuntu
        # 24.04 / Debian bookworm an ECM + Qt6 6.4 "versionless targets" clash
        # breaks the configure; CMake falls back to GNUInstallDirs cleanly.
        REQ=(python3 python3-dbus python3-gi python3-xlib
             cmake ninja-build g++ pkg-config
             qt6-base-dev qt6-declarative-dev)
        OPT=(qml6-module-qtquick qml6-module-qtquick-controls
             qml6-module-qtquick-shapes qml6-module-qtquick-layouts
             qml6-module-qtquick-window liblayershellqtinterface-dev)
        PM_UPDATE="$SUDO apt-get update -qq"
        PM_INSTALL="$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends"
        ;;
    dnf)
        REQ=(python3 python3-dbus python3-gobject python3-xlib
             cmake ninja-build gcc-c++ extra-cmake-modules
             qt6-qtbase-devel qt6-qtdeclarative-devel)
        OPT=(layer-shell-qt-devel)
        PM_INSTALL="$SUDO dnf install -y"
        ;;
    pacman)
        REQ=(python python-dbus python-gobject python-xlib
             cmake ninja extra-cmake-modules gcc
             qt6-base qt6-declarative)
        OPT=(layer-shell-qt)
        PM_UPDATE="$SUDO pacman -Sy --noconfirm"
        PM_INSTALL="$SUDO pacman -S --needed --noconfirm"
        ;;
    zypper)
        REQ=(python3-dbus-python python3-gobject python3-python-xlib
             cmake ninja extra-cmake-modules gcc-c++
             qt6-base-devel qt6-declarative-devel)
        OPT=(layer-shell-qt-devel)
        PM_INSTALL="$SUDO zypper --non-interactive install --no-recommends"
        ;;
    emerge)
        say "Gentoo detected — the cleanest install is the ebuild in packaging/gentoo/"
        say "(see docs/INSTALL.md). Building from your already-installed deps instead."
        WITH_DEPS=0
        ;;
    *)
        say "No supported package manager found ($PRETTY)."
        say "Install the deps listed in docs/INSTALL.md, then re-run with --no-deps."
        WITH_DEPS=0
        ;;
esac

if [ "$DRY" -eq 1 ]; then
    say "distro:           $PRETTY"
    say "package manager:  ${PM:-<none>}"
    say "required deps:    ${REQ[*]:-<none>}"
    say "optional deps:    ${OPT[*]:-<none>}"
    exit 0
fi

if [ "$WITH_DEPS" -eq 1 ] && [ -n "$PM_INSTALL" ]; then
    say "Installing dependencies for $PRETTY"
    eval "$PM_UPDATE"
    # shellcheck disable=SC2086
    $PM_INSTALL "${REQ[@]}"
    if [ "${#OPT[@]}" -gt 0 ]; then
        # shellcheck disable=SC2086
        $PM_INSTALL "${OPT[@]}" || say "note: some optional packages were unavailable (the overlay will build X11-only)"
    fi
fi

say "Building + installing (packaging/install.sh)"
exec "$HERE/packaging/install.sh" "${PASS[@]}"
