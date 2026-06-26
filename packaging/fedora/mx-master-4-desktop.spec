%global appname    mx-master-4-desktop
# Private libdir that hosts the daemon python package + the mx4d launcher
# resolves it via PYTHONPATH. NO venv, NO pip at runtime (system python only).
%global mx4libdir  %{_prefix}/lib/mx4desktop

Name:           mx-master-4-desktop
Version:        0.1.0
Release:        1%{?dist}
Summary:        Native haptics and Actions Ring radial menu for the Logitech MX Master 4

License:        MIT
URL:            https://github.com/UsiDiamond/mx-master-4-linux-desktop
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  cmake
BuildRequires:  ninja-build
BuildRequires:  gcc-c++
BuildRequires:  extra-cmake-modules
BuildRequires:  qt6-qtbase-devel
BuildRequires:  qt6-qtdeclarative-devel
# QuickControls2 C++ module for the config GUI. The config-ui CMakeLists looks
# this up QUIET/optional, so the build is green without it (it falls back to the
# runtime QML import), but providing it completes the C++ component link.
BuildRequires:  qt6-qtquickcontrols2-devel
BuildRequires:  layer-shell-qt-devel

# Daemon (mx4d) runtime — runs on the SYSTEM python, no venv/pip.
Requires:       python3
Requires:       python3-dbus
Requires:       python3-gobject
Requires:       python3-xlib
# Overlay (mx4-radial) + config GUI (mx4-config) runtime: Qt6 + LayerShellQt.
# qt6-qtdeclarative ships the QtQuick / QtQuick.Layouts / QtQuick.Shapes QML
# modules the overlay uses; the config GUI also imports QtQuick.Controls, which
# on Fedora lives in the SEPARATE qt6-qtquickcontrols2 package (without it the
# settings window renders blank controls).
Requires:       qt6-qtbase
Requires:       qt6-qtdeclarative
Requires:       qt6-qtquickcontrols2
Requires:       layer-shell-qt
# mx4-playpause prefers qdbus6 (Qt6 D-Bus CLI, shipped by qt6-qttools) to drive
# MPRIS PlayPause; mx4-show and the dbus-send fallback paths use dbus-send.
Requires:       qt6-qttools
Requires:       dbus-tools

# Pull the active user's udev ACL helper. The KWin focus-bridge is shipped as
# DATA only (NEVER a hard Plasma dep); installs run fine on LXQt/GNOME/etc.

%description
mx-master-4-desktop adds native haptic feedback and an on-screen Actions Ring
radial menu to the Logitech MX Master 4 on Linux desktops. It is INIT-AGNOSTIC
(systemd or OpenRC/runit/s6 via a portable XDG autostart entry) and DE-AWARE
(the optional KWin focus-bridge is Plasma-Wayland-only and is shipped as data,
never enabled by default).

Components:
  * mx4d        - the daemon (system python; talks HID++ to the receiver; it
                  lazy-launches the overlay on demand)
  * mx4-radial  - the Qt6/QML radial-menu overlay (Wayland layer-shell + X11)
  * mx4-config  - the Qt6/QML settings GUI

The single privileged bit is a udev rule that grants the active local session
user (uaccess) access to the Logitech hidraw node; no root is needed at runtime.

%prep
%autosetup -n %{name}-%{version}

%build
# Both C++ components build out-of-tree with CMake + Ninja. ECM/extra-cmake-modules
# is present (BuildRequires), so KDEInstallDirs is used; both CMakeLists fall back
# to GNUInstallDirs if ECM were absent.
%cmake -S overlay -B %{_vpath_builddir}-overlay -G Ninja
%cmake_build --target mx4-radial -C %{_vpath_builddir}-overlay 2>/dev/null || \
    cmake --build %{_vpath_builddir}-overlay

%cmake -S config-ui -B %{_vpath_builddir}-config -G Ninja
%cmake_build --target mx4-config -C %{_vpath_builddir}-config 2>/dev/null || \
    cmake --build %{_vpath_builddir}-config

%install
# --- binaries (overlay + config GUI) ---------------------------------------
install -Dpm0755 %{_vpath_builddir}-overlay/mx4-radial %{buildroot}%{_bindir}/mx4-radial
install -Dpm0755 %{_vpath_builddir}-config/mx4-config  %{buildroot}%{_bindir}/mx4-config

# --- config GUI .desktop ----------------------------------------------------
install -Dpm0644 config-ui/mx4-config.desktop \
    %{buildroot}%{_datadir}/applications/mx4-config.desktop

# --- daemon python package (system python, no venv/pip) ---------------------
# Land the package tree under a private libdir; the launcher points PYTHONPATH
# at it. Strip caches/compiled artifacts.
mkdir -p %{buildroot}%{mx4libdir}/mx4d
( cd daemon/mx4d && \
  find . -name '__pycache__' -prune -o -name '*.pyc' -prune -o -type f -print0 | \
  while IFS= read -r -d '' f; do
      install -Dpm0644 "$f" "%{buildroot}%{mx4libdir}/mx4d/$f"
  done )

# --- daemon launcher (mx4d) -------------------------------------------------
# Runs the SYSTEM python with PYTHONPATH at the private libdir. mx4d is on PATH
# in /usr/bin so the XDG autostart Exec=mx4d resolves with no rewrite.
cat > %{buildroot}%{_bindir}/mx4d <<EOF
#!/usr/bin/sh
# mx4d launcher (rpm). Runs the daemon on the system python, no virtualenv:
# PYTHONPATH points at the installed package tree.
export PYTHONPATH="%{mx4libdir}\${PYTHONPATH:+:\$PYTHONPATH}"
exec %{__python3} -m mx4d "\$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/mx4d

# --- shell helpers (mx4-show + mx4-playpause) -------------------------------
# mx4-show       : dbus-send ShowMenu wrapper (bind to a hotkey/spare button).
# mx4-playpause  : MPRIS play/pause toggle via qdbus6/qdbus/dbus-send, no
#                  playerctl (for a radial "Play / Pause" segment or a hotkey).
install -Dpm0755 packaging/bin/mx4-show      %{buildroot}%{_bindir}/mx4-show
install -Dpm0755 packaging/bin/mx4-playpause %{buildroot}%{_bindir}/mx4-playpause

# --- udev rule (the one privileged bit; vendor-distributed path) ------------
install -Dpm0644 packaging/udev/70-mx-master-4.rules \
    %{buildroot}%{_prefix}/lib/udev/rules.d/70-mx-master-4.rules

# --- portable XDG autostart (primary, init-agnostic) ------------------------
# System package: ship to /etc/xdg/autostart with Exec=mx4d (mx4d is on PATH).
# Only the daemon autostarts; it lazy-launches the overlay.
install -Dpm0644 packaging/autostart/mx4desktop.desktop \
    %{buildroot}%{_sysconfdir}/xdg/autostart/mx4desktop.desktop

# --- systemd user units (systemd-only bonus; harmless data otherwise) -------
install -Dpm0644 packaging/systemd/mx4desktop.service \
    %{buildroot}%{_userunitdir}/mx4desktop.service
install -Dpm0644 packaging/systemd/mx4-overlay.service \
    %{buildroot}%{_userunitdir}/mx4-overlay.service

# --- KWin focus-bridge (Plasma-Wayland only; DATA ONLY, never enabled) ------
# Shipped under the KWin scripts data dir so a Plasma user can opt in; the
# package must NOT require Plasma and the script is EnabledByDefault=false.
install -Dpm0644 packaging/kwin/metadata.json \
    %{buildroot}%{_datadir}/kwin/scripts/mx4-focus-bridge/metadata.json
install -Dpm0644 packaging/kwin/contents/code/main.js \
    %{buildroot}%{_datadir}/kwin/scripts/mx4-focus-bridge/contents/code/main.js

# --- Solaar helper files (opt-in; data only, user runs setup manually) ------
install -Dpm0644 packaging/solaar/mx4-rules.yaml \
    %{buildroot}%{_datadir}/mx4desktop/solaar/mx4-rules.yaml
install -Dpm0644 packaging/solaar/README.md \
    %{buildroot}%{_datadir}/mx4desktop/solaar/README.md
install -Dpm0755 packaging/solaar/setup-solaar.sh \
    %{buildroot}%{_datadir}/mx4desktop/solaar/setup-solaar.sh

%files
%license LICENSE
%doc README.md docs/INSTALL.md docs/ARCHITECTURE.md
%{_bindir}/mx4d
%{_bindir}/mx4-radial
%{_bindir}/mx4-config
%{_bindir}/mx4-show
%{_bindir}/mx4-playpause
%{_datadir}/applications/mx4-config.desktop
%dir %{mx4libdir}
%{mx4libdir}/mx4d/
%{_prefix}/lib/udev/rules.d/70-mx-master-4.rules
%{_sysconfdir}/xdg/autostart/mx4desktop.desktop
%{_userunitdir}/mx4desktop.service
%{_userunitdir}/mx4-overlay.service
%dir %{_datadir}/kwin/scripts/mx4-focus-bridge
%{_datadir}/kwin/scripts/mx4-focus-bridge/metadata.json
%{_datadir}/kwin/scripts/mx4-focus-bridge/contents/code/main.js
%dir %{_datadir}/mx4desktop
%dir %{_datadir}/mx4desktop/solaar
%{_datadir}/mx4desktop/solaar/mx4-rules.yaml
%{_datadir}/mx4desktop/solaar/README.md
%{_datadir}/mx4desktop/solaar/setup-solaar.sh

%post
# Reload udev so the uaccess rule for the Logitech receiver applies immediately
# (re-plug the Bolt receiver if access is still denied). Non-fatal in chroots.
if [ -x %{_bindir}/udevadm ] || command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload >/dev/null 2>&1 || :
    udevadm trigger --subsystem-match=hidraw >/dev/null 2>&1 || :
fi

%changelog
* Thu Jun 25 2026 UsiDiamond <noreply@usidiamond.dev> - 0.1.0-1
- Ship the mx4-playpause MPRIS helper (install + %%files).
- Add qt6-qtquickcontrols2 runtime Requires so the config GUI's QtQuick.Controls
  imports resolve (Fedora splits Controls 2 out of qt6-qtdeclarative).
- Add qt6-qttools (qdbus6) + dbus-tools (dbus-send) Requires for the mx4-playpause
  and mx4-show D-Bus helpers.
- Add qt6-qtquickcontrols2-devel BuildRequires to complete the config GUI's
  QuickControls2 C++ component link.
- Initial Fedora package: init-agnostic, DE-aware MX Master 4 Linux Desktop addon
  (mx4d daemon + mx4-radial overlay + mx4-config GUI), portable XDG autostart,
  systemd user units, vendor udev rule, and Plasma-only KWin focus-bridge data.
