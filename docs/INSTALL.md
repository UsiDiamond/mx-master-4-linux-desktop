# Installing mx-master-4-desktop

This addon has three runtime components and a few data files. It is
**init-agnostic** (systemd *or* OpenRC / runit / s6 / …) and **DE-aware** (KDE
Plasma 6 and LXQt; the core is DE-agnostic):

| Component | What it is | Built / shipped as |
|---|---|---|
| `mx4d` | the daemon (raw HID++, haptics, Actions-Ring trigger) | a Python package run on the **system** python via a launcher — **no venv, no pip at runtime** |
| `mx4-radial` | the radial-menu overlay | a C++/Qt6 + QML binary (CMake) |
| `mx4-config` | the settings GUI | a C++/Qt6 + QML binary (CMake) |
| config | shared INI | `~/.config/mx4desktop/config.ini`, written with sane defaults on first run |
| udev rule | grants the session r/w on the receiver's hidraw node | `70-mx-master-4.rules` (`uaccess`, Logitech VID `046d`) |
| autostart | portable login autostart | XDG `mx4desktop.desktop` (`Exec=mx4d-supervise mx4d`) |
| KWin script | native-Wayland focus bridge | `mx4-focus-bridge` — **Plasma-Wayland-only, installed not enabled** |

> **Only the daemon needs to autostart.** It lazy-launches the overlay on demand
> (and on the Actions-Ring trigger), so you never autostart the overlay yourself.

> **`mx4d-supervise`** relaunches the daemon with backoff so a device that is
> still asleep at login (Bolt wake latency), or one that goes to sleep
> mid-session, doesn't leave haptics dead until the next login — see the
> comments in `packaging/autostart/mx4desktop.desktop`. `packaging/install.sh`
> installs it to `~/.local/bin/mx4d-supervise` and rewrites `Exec=` to absolute
> paths. **The Arch/Debian/Fedora/Gentoo packaging recipes currently ship the
> autostart template as-is without installing `mx4d-supervise` to `/usr/bin`**,
> so autostart from a distro package currently has no supervisor on `PATH` —
> use `packaging/install.sh` if you hit this.

## Dependencies

**Runtime**

- Python 3.11+ with, in the **system** site-packages: `python-dbus`, **PyGObject**
  (`gi`), and **python-Xlib**. Optional: `pactl` (PulseAudio) or `pw-mon`
  (PipeWire) for the opt-in system-sound source; each missing optional dep just
  disables that one source.
- Qt6 (`Core Gui Qml Quick QuickControls2 DBus`) + **LayerShellQt** for the
  overlay and the config GUI, plus the QML runtime modules
  (`QtQuick`, `QtQuick.Controls`, `QtQuick.Shapes`).

**Build**

- `cmake` (≥ 3.16), `ninja` (or make), a C++17 compiler (`gcc`/`g++`),
  `extra-cmake-modules` (ECM — optional; falls back to `GNUInstallDirs`),
  and the Qt6 **dev** packages + **LayerShellQt** dev headers.

---

## Quick start (from source, any distro)

```bash
git clone https://github.com/UsiDiamond/mx-master-4-linux-desktop
cd mx-master-4-linux-desktop
packaging/install.sh                 # builds + installs under ~/.local (one sudo step for udev)
packaging/install.sh --enable-autostart   # …and start mx4d at every login
```

`install.sh` is **idempotent** and:

- builds `mx4-radial` + `mx4-config` (CMake) → `~/.local/bin/`,
- installs the daemon package → `~/.local/lib/mx4desktop/mx4d/` + a `~/.local/bin/mx4d`
  launcher (system python, no venv),
- installs a **portable XDG autostart template** →
  `~/.local/share/mx4desktop/autostart/mx4desktop.desktop` (enable with
  `--enable-autostart`, or copy it to `~/.config/autostart/`),
- **detects the init system**: on systemd it *also* installs the systemd **user**
  units and prints `systemctl --user` commands; on OpenRC / anything else it
  prints `mx4d &` / `pkill` guidance and **never calls systemctl**,
- **detects the desktop**: installs the KWin focus-bridge **only on Plasma**; on
  LXQt/X11 it is skipped (the daemon's `_NET_ACTIVE_WINDOW` focus source is
  native and complete there),
- installs the udev rule to `/etc/udev/rules.d/` (the one `sudo` step; skip with
  `--no-udev`),
- writes the default config **only if none exists** (never overwrites yours).

Useful flags: `--enable-autostart`, `--no-udev`, `--prefix DIR` (install under
`DIR` instead of `~/.local`).

### Starting / stopping

**systemd (user manager present):**

```bash
systemctl --user start  mx4desktop.service mx4-overlay.service   # this session
systemctl --user enable --now mx4desktop.service mx4-overlay.service   # every login
systemctl --user stop   mx4-overlay.service mx4desktop.service   # graceful: restores the panel
```

**OpenRC / runit / s6 / no systemd user manager:**

```bash
mx4d --verbose &                          # daemon; lazy-launches the overlay on demand
pkill -TERM -f 'python.* -m mx4d'         # stop (graceful: restores the Actions Ring panel)
# autostart at login (no systemd):
packaging/install.sh --enable-autostart
#   or: cp ~/.local/share/mx4desktop/autostart/mx4desktop.desktop ~/.config/autostart/
```

Either way: edit settings with `mx4-config` (or "MX Master 4 Settings" in the menu),
and trigger the ring without a hardware tap with:

```bash
dbus-send --session --dest=dev.usidiamond.mx4 /dev/usidiamond/mx4 \
  dev.usidiamond.mx4.Daemon.ShowMenu string:default
```

### Uninstall

```bash
packaging/uninstall.sh           # keeps your config
packaging/uninstall.sh --purge   # also removes ~/.config/mx4desktop/
```

It stops the daemon **first** (SIGTERM → restores the diverted Actions Ring panel),
then removes the binaries, daemon, autostart entry, systemd units (if any), and the
KWin script. It never deletes an autostart entry that is not ours.

### Wayland vs X11 (read this once)

- **Plasma 6 / Wayland:** the overlay appears **center-screen** (a Wayland client
  cannot read the global cursor or place a surface at an absolute x,y). This is
  correct, not a bug. Native-Wayland focus haptics need the optional
  **`mx4-focus-bridge` KWin script** (installed, not enabled):

  ```bash
  kwriteconfig6 --file kwinrc --group Plugins --key mx4-focus-bridgeEnabled true
  qdbus6 org.kde.KWin /KWin reconfigure
  # (or System Settings > Window Management > KWin Scripts)
  ```

- **X11 / LXQt (and Plasma-X11):** the overlay appears **at the cursor**, and
  focus haptics work natively via `_NET_ACTIVE_WINDOW` — **no KWin script needed**.

---

## Gentoo

Gentoo is the reference distro for the **OpenRC** path. The package defaults to
**XDG autostart** (no systemd needed) and gates the systemd user units behind a
`systemd` USE flag.

### Option A — package install via a local overlay (recommended)

Add the ebuild through a local overlay so Portage tracks the install. The ebuild
lives in the companion packaging repo / `packaging/gentoo/` (category
`x11-misc/mx-master-4-desktop`).

1. **Create a local overlay** (once):

   ```bash
   sudo eselect repository create local           # creates /var/db/repos/local
   # …or by hand:
   sudo install -d /var/db/repos/local/{metadata,profiles}
   echo 'masters = gentoo' | sudo tee /var/db/repos/local/metadata/layout.conf
   echo 'local'            | sudo tee /var/db/repos/local/profiles/repo_name
   # register it (if not using eselect repository):
   sudo install -d /etc/portage/repos.conf
   printf '[local]\nlocation = /var/db/repos/local\nmasters = gentoo\nauto-sync = no\n' \
     | sudo tee /etc/portage/repos.conf/local.conf
   ```

2. **Drop the ebuild in and digest it:**

   ```bash
   sudo install -d /var/db/repos/local/x11-misc/mx-master-4-desktop
   sudo cp packaging/gentoo/x11-misc/mx-master-4-desktop/mx-master-4-desktop-*.ebuild \
           packaging/gentoo/x11-misc/mx-master-4-desktop/metadata.xml \
           /var/db/repos/local/x11-misc/mx-master-4-desktop/
   sudo ebuild /var/db/repos/local/x11-misc/mx-master-4-desktop/mx-master-4-desktop-*.ebuild manifest
   ```

3. **Set USE flags** (OpenRC default needs none; opt into systemd user units if
   you run systemd):

   ```bash
   # /etc/portage/package.use/mx-master-4-desktop
   x11-misc/mx-master-4-desktop -systemd        # OpenRC (default); use +systemd on systemd
   ```

4. **Emerge:**

   ```bash
   sudo emerge -av x11-misc/mx-master-4-desktop
   ```

   This pulls the runtime deps (`dev-python/dbus-python`, `dev-python/pygobject`,
   `dev-python/python-xlib`, `dev-qt/qtbase[dbus]`, `dev-qt/qtdeclarative`,
   `kde-plasma/layer-shell-qt`), installs `mx4d` / `mx4-radial` / `mx4-config`
   into `/usr/bin`, the udev rule into `/usr/lib/udev/rules.d/`, the XDG
   autostart entry into `/etc/xdg/autostart/` (or the per-user template), and —
   only with `USE=systemd` — the user units into `/usr/lib/systemd/user/`.

5. **Reload udev** and **autostart on OpenRC:**

   ```bash
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=hidraw     # or re-plug the Bolt receiver
   # OpenRC has no `systemctl --user`. Start it now:
   mx4d --verbose &
   # autostart at login is via XDG; the package ships /etc/xdg/autostart/mx4desktop.desktop
   # (system-wide) — or copy the per-user template to ~/.config/autostart/.
   ```

> **`systemctl --user` does not exist on OpenRC.** Do not look for it. Autostart
> is XDG; manual start is `mx4d &`; stop is `pkill -TERM -f 'python.* -m mx4d'`.

### Option B — from source on Gentoo (no ebuild)

Install the deps, then run the source installer (it auto-detects OpenRC and uses
XDG autostart):

```bash
sudo emerge -av dev-python/dbus-python dev-python/pygobject dev-python/python-xlib \
  dev-qt/qtbase dev-qt/qtdeclarative kde-plasma/layer-shell-qt \
  dev-build/cmake dev-build/ninja kde-frameworks/extra-cmake-modules
packaging/install.sh --enable-autostart
```

On LXQt the KWin script is skipped automatically; on Plasma it is installed
(not enabled).

---

## Arch / Manjaro

```bash
# deps
sudo pacman -S --needed python python-dbus python-gobject python-xlib \
  qt6-base qt6-declarative qt6-wayland layer-shell-qt cmake ninja extra-cmake-modules gcc
# from source:
packaging/install.sh --enable-autostart
```

Arch is systemd, so `install.sh` also installs the user units; enable with
`systemctl --user enable --now mx4desktop.service mx4-overlay.service`.
(A PKGBUILD installs into `/usr/bin`, `/usr/lib/udev/rules.d`,
`/usr/lib/systemd/user`, and `/etc/xdg/autostart`.)

## Debian / Ubuntu

```bash
sudo apt install python3 python3-dbus python3-gi python3-xlib \
  qt6-base-dev qt6-declarative-dev liblayershellqtinterface-dev \
  cmake ninja-build g++   # extra-cmake-modules is OPTIONAL — omit it on
                          # Ubuntu 24.04 / Debian bookworm to avoid an ECM+Qt6
                          # versionless-target conflict; CMake falls back to
                          # GNUInstallDirs cleanly.
packaging/install.sh --enable-autostart
```

systemd: enable with `systemctl --user enable --now mx4desktop.service mx4-overlay.service`.
A `.deb` installs into `/usr/bin`, `/lib/udev/rules.d`, `/usr/lib/systemd/user`,
and `/etc/xdg/autostart` (LayerShellQt dev package name may be
`liblayershellqtinterface-dev` or `qml6-module-org-kde-layershell` depending on
release — verify on the target).

## Fedora

```bash
sudo dnf install python3 python3-dbus python3-gobject python3-xlib \
  qt6-qtbase-devel qt6-qtdeclarative-devel layer-shell-qt-devel \
  cmake ninja-build extra-cmake-modules gcc-c++
packaging/install.sh --enable-autostart
```

systemd: enable with `systemctl --user enable --now mx4desktop.service mx4-overlay.service`.
An `.rpm` installs into `/usr/bin`, `/usr/lib/udev/rules.d`,
`/usr/lib/systemd/user`, and `/etc/xdg/autostart`.

---

## Triggering the ring

The menu opens when the daemon receives `ShowMenu` over D-Bus. Pick whichever way
fits how you want to use the mouse:

1. **A global hotkey or a spare button — recommended, changes nothing else.** Bind the
   installed `mx4-show` helper to a shortcut:
   - **KDE Plasma:** System Settings → Shortcuts → Custom Shortcuts → new → command `mx4-show`.
   - **LXQt:** Preferences → Shortcut Keys → add → command `mx4-show`.

   This does **not** alter any mouse button's existing behaviour.

2. **The haptic touch panel — this REPLACES what the panel does today.** Diverting the
   panel to open the ring *takes it over*, so it stops doing whatever it did before
   (e.g. a window/focus action). Enable only if you want the panel to *be* the ring:
   - Standalone: `[trigger] divert_panel = true` (the daemon captures the panel itself).
   - Solaar-first: `divert_panel = auto` (default — when Solaar is running the daemon
     does **not** divert; divert the *Haptic* control in Solaar once and the daemon
     listens for it, giving you tap **and** hold). No Solaar rule needed — see
     `packaging/solaar/README.md`.

3. **Directly, for testing:** `mx4-show` (or the raw `dbus-send … ShowMenu`).

> **A mouse button stopped doing its old job?** That's the panel/control having been
> *diverted* for the ring. Restore it: set `[trigger] divert_panel = false` (and, if you
> used the Solaar path, set its diversion back to *Regular* in Solaar's UI), then trigger
> the ring with `mx4-show` on a hotkey instead. `divert_panel = auto` only diverts the
> panel when Solaar is **not** running; `false` guarantees the panel is never touched.

---

## Troubleshooting

- **Daemon can't open the device / permission denied:** the udev rule grants
  `uaccess` to the *active local session*. Re-plug the Bolt receiver or
  `sudo udevadm trigger --subsystem-match=hidraw`. Never run the daemon as root.
- **`mx4d: command not found`:** add `~/.local/bin` to `PATH`
  (`export PATH="$HOME/.local/bin:$PATH"`), or use the package install (`/usr/bin`).
- **Ring appears center-screen on Wayland:** expected (see *Wayland vs X11*).
- **Some waveforms do nothing:** waveforms are **firmware-gated**; the daemon
  falls back to the nearest supported one. `mx4-config` marks unsupported
  waveforms once the daemon is running.
