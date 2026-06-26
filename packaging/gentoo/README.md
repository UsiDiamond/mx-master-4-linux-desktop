# mx4 — Gentoo Portage overlay for mx-master-4-desktop

This directory is a **standalone Portage overlay** (repo name `mx4`) that ships
`x11-misc/mx-master-4-desktop`: the Actions Ring radial overlay (`mx4-radial`),
the settings GUI (`mx4-config`) and the native-haptics daemon (`mx4d`) for the
Logitech MX Master 4 on Plasma 6 / LXQt.

It inherits everything (eclasses, profiles, virtuals, the atoms it depends on)
from the main `::gentoo` tree via `metadata/layout.conf` (`masters = gentoo`).

## Two ebuilds

| Ebuild                              | Source              | Use it when                          |
|-------------------------------------|---------------------|--------------------------------------|
| `mx-master-4-desktop-9999.ebuild`   | `git-r3` (upstream HEAD) | **NOW** — builds today, no tag needed |
| `mx-master-4-desktop-0.1.0.ebuild`  | release tarball     | after upstream cuts a `v0.1.0` git tag |

There is **no `v0.1.0` git tag upstream yet**, so the versioned ebuild's
`SRC_URI` 404s until one is cut. Emerge `=mx-master-4-desktop-9999` to build the
current source today.

## Install (end user)

### 1. Add the overlay

Either with `eselect repository` (if you have `app-eselect/eselect-repository`),
pointing at this checkout:

```sh
# clone the repo, then register packaging/gentoo as the "mx4" overlay:
eselect repository add mx4 git https://github.com/UsiDiamond/mx-master-4-linux-desktop.git
# (the overlay lives in the packaging/gentoo subdir; see the manual repos.conf
#  form below if you want to point straight at a local checkout subdir)
```

Or by hand via `/etc/portage/repos.conf/mx4.conf` (works with a local checkout —
point `location` at the `packaging/gentoo` subdirectory):

```ini
[mx4]
location = /path/to/mx-master-4-desktop/packaging/gentoo
sync-type = git
sync-uri = https://github.com/UsiDiamond/mx-master-4-linux-desktop.git
auto-sync = no
masters = gentoo
```

Then make the live ebuild visible and emerge it:

```sh
# allow the live (9999) ebuild:
echo "=x11-misc/mx-master-4-desktop-9999 **" \
    | sudo tee /etc/portage/package.accept_keywords/mx4 >/dev/null

# OpenRC / runit / s6 box: leave systemd USE off (default) — XDG autostart is used.
# systemd box that wants the user units: enable USE=systemd:
#   echo "x11-misc/mx-master-4-desktop systemd" \
#       | sudo tee /etc/portage/package.use/mx4 >/dev/null

sudo emerge --ask =x11-misc/mx-master-4-desktop-9999
```

### USE flags

- `sound` (default **on**): pull in PulseAudio (`pactl`) or PipeWire (`pw-mon`)
  so the opt-in system-sound haptic source has a monitor. Off just disables
  that one ambient source.
- `systemd` (default **off**): install the systemd **user** units. With it off
  (the right default on OpenRC) the portable XDG autostart entry handles login.

## What gets installed

- `/usr/bin/mx4-radial`, `/usr/bin/mx4-config` — Qt6/QML binaries (CMake).
- `/usr/bin/mx4d` — launcher: runs the **system** python as `python -m mx4d`
  with `PYTHONPATH` at the staged package (no venv, no pip).
- `/usr/lib/mx-master-4-desktop/mx4d/` — the daemon Python package.
- `/usr/bin/mx4-show`, `/usr/bin/mx4-playpause` — shell helpers.
- `/usr/share/applications/mx4-config.desktop` — menu entry.
- `/usr/lib/udev/rules.d/70-mx-master-4.rules` — `uaccess` hidraw ACL.
- `/etc/xdg/autostart/mx4desktop.desktop` — portable autostart (daemon only).
- `/usr/lib/systemd/user/*.service` — **only** with `USE=systemd`.
- `/usr/share/kwin/scripts/mx4-focus-bridge/` — shipped as data, never enabled
  (Plasma-Wayland opt-in).

The daemon never runs as root; the udev rule grants the session user hidraw
access. The default `~/.config/mx4desktop/config.ini` is generated on first run.
