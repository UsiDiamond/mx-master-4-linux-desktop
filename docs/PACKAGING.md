# Packaging & Install Guide — mx-master-4-desktop

Canonical packaging and install documentation for **mx-master-4-desktop**, covering Gentoo
(portage overlay + emerge), Debian/Ubuntu (apt/dpkg), Arch (pacman/makepkg), and Fedora
(dnf/rpmbuild).

## Overview

- **License:** MIT (see `LICENSE` at the repo root).
- **Version:** 0.1.0.
- **Runtime model:** the daemon runs on the **system Python** — there is **no virtualenv** —
  and it **never runs as root**. It runs as a per-user session process (XDG autostart or, where
  available, a `systemctl --user` unit). Hardware access is granted by the shipped udev
  `uaccess` rule, not by privilege.
- **Two userland helpers** are shipped and must be present in every package:
  - `mx4-show` — invokes the Actions Ring overlay (requires `dbus-send`).
  - `mx4-playpause` — MPRIS play/pause helper. Prefers `qdbus6`; falls back to `dbus-send`
    when `qdbus6` is not on `PATH`. (This helper was the recurring gap fixed across all four
    distros — earlier packaging predated the file and omitted it.)

After installing on any distro, **re-plug the Logitech Bolt receiver once** so the shipped udev
uaccess rule grants your login session access to the device, then run `mx4-config` to set up
haptics and the Actions Ring.

### Build status at a glance

No distro had a full from-source package build executed during this packaging pass — the host is
a Gentoo box mid an unrelated heavy `@world` rebuild, and each real build would pull a full Qt6
CMake toolchain and compile two Qt6/QML projects (the radial overlay and the config UI), which
would not finish quickly and would contend with the in-progress rebuild. Each distro's packaging
was instead **lint-checked / statically verified**, and every dependency name was cross-checked
against the relevant live package database. See each distro's *Residual risks* section.

| Distro | Packaging verified | Full build run | Notes |
|--------|--------------------|----------------|-------|
| Gentoo | Yes (bash -n + ebuild metadata source + overlay registration) | No — packaging is lint-checked; full build not yet run on Gentoo | No v0.1.0 git tag yet → use the live `9999` ebuild |
| Debian/Ubuntu | Yes (bash -n + `make -f rules -n` + offline structural validation) | No — packaging is lint-checked; full build not yet run on Debian | `dpkg-buildpackage`/`lintian` unavailable on the Gentoo host |
| Arch | Yes (bash -n + source-and-dump SRCINFO emulation) | No — packaging is lint-checked; full build not yet run on Arch | No release tag → local `git archive` tarball, or AUR `-git` variant |
| Fedora | Yes (rpmlint 2.8.0, spec-only — 0 errors, 2 benign warnings) | No — packaging is lint-checked; full build not yet run on Fedora | `build-in-docker.sh` corrected and ready to run on an idle box |

---

## Gentoo (portage overlay + emerge)

The packaging under `packaging/gentoo/` is now a **standalone overlay** (repo name `mx4`,
`masters = gentoo`, thin manifests) containing `x11-misc/mx-master-4-desktop`.

### Add the overlay and install

```sh
# 1. Register the standalone overlay (repo name 'mx4'):
sudo eselect repository add mx4 git https://github.com/UsiDiamond/mx-master-4-linux-desktop.git
#    (or a manual /etc/portage/repos.conf/mx4.conf with location=<checkout>/packaging/gentoo, masters=gentoo)
sudo emaint sync -r mx4
# 2. Allow the live (9999) ebuild — there is no v0.1.0 tag yet, so 9999 is the build-today path:
echo '=x11-misc/mx-master-4-desktop-9999 **' | sudo tee /etc/portage/package.accept_keywords/mx4
# 3. (OpenRC box: leave systemd USE off — XDG autostart is used. systemd box wanting user units:)
#    echo 'x11-misc/mx-master-4-desktop systemd' | sudo tee /etc/portage/package.use/mx4
# 4. Emerge it:
sudo emerge --ask =x11-misc/mx-master-4-desktop-9999
```

### Build from source vs. install a built package

Gentoo is source-based: `emerge` compiles the Qt6 C++ in `overlay/` and `config-ui/` from the
checkout. There are **two ebuilds**:

- `mx-master-4-desktop-9999.ebuild` — **the build-today path.** A live `git-r3` ebuild
  (`EGIT_REPO_URI`, empty `KEYWORDS`, `git-r3_src_unpack`). Use this because there is no upstream
  `v0.1.0` tag yet.
- `mx-master-4-desktop-0.1.0.ebuild` — a versioned ebuild whose `SRC_URI` currently **404s**
  (no tag exists). Once upstream cuts a `v0.1.0` tag, re-run `ebuild …-0.1.0.ebuild manifest`
  and the versioned path becomes usable.

### Dependencies

Atom names were verified against the local `::gentoo` tree.

- **Build:** `dev-build/cmake`, `kde-frameworks/extra-cmake-modules`,
  `dev-qt/qtbase:6[dbus,gui]`, `dev-qt/qtdeclarative:6`, `kde-plasma/layer-shell-qt:6`
  (note: **`kde-plasma/`**, not `gui-libs/` or `kde-frameworks/`).
- **Runtime (RDEPEND):** `dev-python/pygobject:3`, `media-sound/pulseaudio-daemon`,
  `media-video/pipewire`, plus the helper transports `sys-apps/dbus` (the always-present
  `dbus-send` fallback) and `dev-qt/qttools:6[qdbus]` (`qdbus6`, the preferred `mx4-playpause`
  path).

### What was fixed

- `mx4-playpause` was not being installed (the ebuild only did `dobin mx4-show`); added
  `dobin packaging/bin/mx4-playpause` to `src_install` in **both** ebuilds.
- Made it a standalone overlay: added `metadata/layout.conf`, `profiles/repo_name` (`mx4`) and
  `profiles/categories` (`x11-misc`).
- Added the live `9999` ebuild as the build-today path; annotated the `0.1.0` `SRC_URI` that a
  tag must be cut.
- Added the `mx4-playpause` transport deps (`sys-apps/dbus`, `dev-qt/qttools:6[qdbus]`).

### Residual risks / caveats

- **No real cmake/emerge build was performed** (too heavy mid the unrelated `@world` rebuild) —
  the Qt6 C++ compile and actual file-landing were not exercised end-to-end; only metadata and
  file-presence were validated statically. *Packaging is lint-checked; full build not yet run on
  Gentoo.*
- `ebuild manifest` was deliberately not run (the `9999` manifest step triggers a live git
  fetch). With `thin-manifests=true` the `9999` ebuild needs no DIST Manifest; the `0.1.0`
  ebuild **will** need `ebuild … manifest` re-run once a `v0.1.0` tag exists.
- `pkgcheck`/`repoman`/`pkgdev` are not installed on this box, so deeper QA lint (metadata.xml
  schema, dependency graph, style) could not run — only `bash -n` + portage metadata sourcing
  (both ebuilds sourced clean; `portageq get_repos` lists `mx4` as a valid overlay).
- `EGIT_REPO_URI` assumes the upstream default branch builds; if upstream HEAD diverges from a
  buildable state, the live ebuild inherits that.
- `dev-qt/qttools:6[qdbus]` is a hard `RDEPEND` for the preferred `mx4-playpause` path. It is a
  modest extra dep (`qdbus6`); a maintainer wanting it lighter could drop `qttools` and rely on
  the always-present `dbus-send` fallback alone.

---

## Debian / Ubuntu (apt / dpkg)

Packaging lives in `packaging/debian/`. Targets **Debian 12+ (bookworm/trixie) and Ubuntu
24.04+**.

### Build and install the .deb from source

```sh
# Build and install the .deb from source (Debian 12+/Ubuntu 24.04+):
sudo apt update
sudo apt install -y build-essential devscripts debhelper cmake ninja-build pkg-config qt6-base-dev qt6-declarative-dev liblayershellqtinterface-dev python3
cd mx-master-4-linux-desktop
cp -r packaging/debian debian
dpkg-buildpackage -us -uc -b
sudo apt install -y ../mx-master-4-desktop_0.1.0-2_*.deb   # apt pulls runtime deps (python3-dbus, python3-gi, python3-xlib, qml6 modules, dbus-bin, qdbus-qt6, layer-shell runtime)
# Then, per-user: log out/in (or `systemctl --user enable --now mx4desktop.service mx4-overlay.service`), or run `mx4d --verbose &`. Configure with `mx4-config`.
# Re-plug the receiver once so the shipped udev uaccess rule (/lib/udev/rules.d/70-mx-master-4.rules) grants your session access.
```

### Build from source vs. install a built package

There is no prebuilt `.deb` published yet; you build it from the in-tree `packaging/debian/`
directory with `dpkg-buildpackage`, then `apt install` the resulting `.deb` (apt resolves the
runtime dependencies). The current changelog version is **`0.1.0-2`** (the `-2` revision records
the packaging corrections below).

### Dependencies

Package names were cross-checked against the live Debian package database.

- **Build-Depends:** `build-essential`, `debhelper`, `cmake`, `ninja-build`, `pkg-config`,
  `qt6-base-dev`, `qt6-declarative-dev`, `liblayershellqtinterface-dev`, `python3`.
- **Runtime Depends:** `python3` + `python3-dbus`, `python3-gi`, `python3-xlib`; the QML
  modules including `qml6-module-qtquick-templates` (required by the `mx4-config`
  `QtQuick.Controls` QML); `dbus-bin | dbus` (`dbus-send` lives in `dbus-bin` on trixie, `dbus`
  on bookworm); and `liblayershellqtinterface6 | liblayershellqtinterface5` (trixie ships 6.x,
  bookworm/Ubuntu 24.04 ship 5.x).
- **Recommends:** `qdbus-qt6` (provides `/usr/bin/qdbus6` on trixie/Ubuntu — the fast
  `mx4-playpause` path; only a Recommends because bookworm ships `qdbus` off-`PATH`, so the
  `dbus-send` fallback covers it).

### What was fixed

- `debian/rules` did not install `mx4-playpause`; added
  `install -Dm755 packaging/bin/mx4-playpause` to `override_dh_auto_install`.
- Added `Depends: dbus-bin | dbus` (needed by `mx4-show`; fallback for `mx4-playpause`).
- Added `Recommends: qdbus-qt6` for the `qdbus6` fast path.
- Re-pinned the layer-shell runtime to `liblayershellqtinterface6 | liblayershellqtinterface5`
  so Wayland layer-shell resolves on both bookworm/Ubuntu 24.04 (5.x) and trixie (6.x).
- Added `qml6-module-qtquick-templates` to Depends.
- Documented both helpers in the package long description; added the `0.1.0-2` changelog entry.

### Residual risks / caveats

- **Full `dpkg-buildpackage` + `lintian` were not run** (resource-aware skip; no native Debian
  toolchain on the Gentoo host, and the only cached image, `ubuntu:24.04`, lacks
  `dpkg-dev`/`devscripts`/`lintian`). Static structure, makefile parse (`make -f rules -n`),
  shell syntax, and every dependency name were verified instead. *Packaging is lint-checked;
  full build not yet run on Debian.*
- On bookworm, `qdbus-qt6` installs `qdbus` at `/usr/lib/qt6/bin/qdbus` (off `PATH`, not named
  `qdbus6`), so `mx4-playpause` uses the `dbus-send` fallback there — functionally correct;
  `qdbus-qt6` is only a Recommends.
- `Build-Depends liblayershellqtinterface-dev` resolves to 5.27 on bookworm/Ubuntu 24.04 and 6.x
  on trixie; the quilt patch `layershellqt-setdesiredsize-compat.patch` handles the 5.x vs 6.x
  API split, but the actual compile against both was not executed here.
- `shlibs:Depends` will add the concrete `liblayershellqtinterfaceN` runtime at build time from
  the linked `.so`; the explicit Recommends is a belt-and-suspenders fallback for X11-only builds
  where the lib is not linked.

---

## Arch (pacman / makepkg)

Packaging lives in `packaging/arch/` (`PKGBUILD` + `mx-master-4-desktop.install`).
`pkgname=mx-master-4-desktop`, `pkgver=0.1.0`, `pkgrel=1`, `arch=x86_64`, `license=MIT`.

### Build and install

```sh
# Arch / pacman — build & install from this checkout (no release tag exists yet):
cd packaging/arch
( cd ../.. && git archive --format=tar.gz --prefix="mx-master-4-desktop-0.1.0/" -o "packaging/arch/mx-master-4-desktop-0.1.0.tar.gz" HEAD )
makepkg -fi
# then re-plug the Logitech receiver so the uaccess udev rule applies, and run: mx4-config

# Alternative — AUR -git package (builds straight from upstream, no tag needed):
# edit PKGBUILD per the documented -git block (rename pkgname to mx-master-4-desktop-git,
#   set source=("$pkgname::git+https://github.com/UsiDiamond/mx-master-4-linux-desktop.git"), add pkgver()), then:
makepkg -fi
```

### Build from source vs. install a built package

makepkg always builds from source. Because **no upstream release tag exists** (`0.1.0` is only
the in-tree `project()` version), the default `source` is a **local working-tree tarball** built
via `git archive` (with `sha256sums=SKIP`). For AUR distribution, switch to the documented
`-git` variant (`git+https://…` source, `pkgver()` using `rev-list`+`rev-parse`, and the `git`
makedepend) — it builds straight from upstream with no tag needed.

### Dependencies

Package names were validated by sourcing the PKGBUILD and a manifest cross-check.

- **depends:** the Qt6 runtime, layer-shell-qt, the Python deps, plus `qt6-tools` — which
  provides `qdbus6`, the preferred `mx4-playpause` backend and the `qdbus6` used for the KWin
  reconfigure hint. (`mx4-playpause` falls back to `dbus-send` from the always-present `dbus`.)
- **build:** the Qt6/CMake toolchain; `build()`/`package()` build both cmake projects
  (`mx4-radial` and `mx4-config`) with `-DCMAKE_INSTALL_PREFIX=/usr`.

### What was fixed

- Added `mx4-playpause` to `package()` (installed to `/usr/bin/mx4-playpause`, mode 755) — the
  PKGBUILD previously installed only `mx4-show`.
- Added `qt6-tools` to `depends()` for `qdbus6`.
- Documented a buildable-today source story: the local `git archive` tarball plus a complete,
  copy-pasteable AUR `-git` variant.
- Added an end-user note for both helpers to the `.install` `post_install` message.

### Residual risks / caveats

- **No real `makepkg` build or `namcap` run was performed** (`makepkg`/`pacman`/`namcap` are not
  on the Gentoo host, and a Docker Arch build would compile both Qt6/QML projects — too heavy
  mid the unrelated rebuild). `build()`/`package()` were validated only statically and by
  manifest cross-check. *Packaging is lint-checked; full build not yet run on Arch.*
- The default source is a local working-tree tarball (`sha256sums=SKIP`) because no upstream
  release tag exists; an AUR submission should switch to the `-git` variant or a tagged tarball
  with a real checksum.
- `qt6-tools` is a hard depend for `qdbus6`; a future maintainer wanting a leaner closure could
  move it to `optdepends` (since `mx4-playpause` has a `dbus-send` fallback). It is kept as a
  depend to match the manifest.

---

## Fedora (dnf / rpmbuild)

Packaging lives in `packaging/fedora/` (`mx-master-4-desktop.spec` +
`build-in-docker.sh`). Targets current Fedora (F39–F41). `Version: 0.1.0`, `License: MIT`
with `%license LICENSE`.

### Build and install

```sh
# Build + install the RPM in a clean Fedora container (produces an .rpm under ~/rpmbuild/RPMS):
bash packaging/fedora/build-in-docker.sh

# Or build natively on a Fedora host:
sudo dnf install -y rpm-build rpmdevtools rpmlint dnf-plugins-core
rpmdev-setuptree
tar --transform 's,^,mx-master-4-desktop-0.1.0/,' -czf ~/rpmbuild/SOURCES/mx-master-4-desktop-0.1.0.tar.gz -C . --exclude=.git --exclude=overlay/build --exclude=config-ui/build .
cp packaging/fedora/mx-master-4-desktop.spec ~/rpmbuild/SPECS/
sudo dnf builddep -y ~/rpmbuild/SPECS/mx-master-4-desktop.spec
rpmbuild -bb ~/rpmbuild/SPECS/mx-master-4-desktop.spec

# Install the resulting package (pulls Qt6 + qt6-qtquickcontrols2 + qt6-qttools + dbus-tools + python3 deps automatically):
sudo dnf install -y ~/rpmbuild/RPMS/*/mx-master-4-desktop-0.1.0-*.rpm

# Then, as your normal user, autostart the daemon at login (not enabled by default):
cp /etc/xdg/autostart/mx4desktop.desktop ~/.config/autostart/   # OR on systemd:
systemctl --user enable --now mx4desktop.service mx4-overlay.service
# Configure haptics / Actions Ring:  mx4-config   (re-plug the Bolt receiver once after install for udev access)
```

### Build from source vs. install a built package

`rpmbuild -bb` builds the `.rpm` from the spec (compiling `mx4-radial` and `mx4-config` under
`%cmake`); you then `dnf install` the resulting binary RPM, and dnf resolves the runtime
`Requires`. The container path (`build-in-docker.sh`) does the full `rpmbuild` + `rpmlint` +
`rpm -qlp` + requires-dump in a clean `fedora:latest` and is the recommended way to produce a
package on a non-Fedora host.

### Dependencies

Package names were validated against rpmlint's spec parser and current Fedora knowledge (F39–F41).

- **BuildRequires:** the Qt6 devel toolchain — `qt6-qtbase-devel`, `qt6-qtdeclarative-devel`,
  `qt6-qtquickcontrols2-devel` (completes the `QuickControls2` C++ component link),
  `layer-shell-qt-devel`, `gcc-c++`, plus cmake.
- **Runtime Requires:** the Qt6 runtime; `qt6-qtquickcontrols2` (the `mx4-config` QML imports
  `QtQuick.Controls` (Controls 2), split out of `qt6-qtdeclarative` on Fedora — without it the
  config UI renders blank controls); `qt6-qttools` (provides `/usr/bin/qdbus6`, the preferred
  `mx4-playpause` backend — `qt6-qtbase` does not ship it); `dbus-tools` (provides `dbus-send`
  for `mx4-show` and the `mx4-playpause` fallback); and `python3-gobject`, `python3-dbus`,
  `python3-xlib`.

### What was fixed

- **Critical:** `mx4-playpause` was entirely absent from the spec — added
  `install -Dpm0755 packaging/bin/mx4-playpause` to `%install` and `%{_bindir}/mx4-playpause` to
  `%files` (rpm fails on unpackaged files / would otherwise silently omit the binary).
- Added runtime `Requires`: `qt6-qtquickcontrols2`, `qt6-qttools`, `dbus-tools`.
- Added `BuildRequires: qt6-qtquickcontrols2-devel`.
- Extended `build-in-docker.sh`'s dependency-probe loop to cover the new names.
- Updated `%changelog` (dated 2026-06-25) documenting the additions.

### Residual risks / caveats

- **No full `rpmbuild` executed**, so the actual `%cmake` compile of `mx4-radial`/`mx4-config`
  and the runtime resolution of the new Requires were not exercised end-to-end. Run
  `packaging/fedora/build-in-docker.sh` on an idle box to confirm. Fast `rpmlint` static lint was
  run and **passed: 0 errors, 2 benign warnings** (`no-%check-section` and `invalid-url Source0`
  — both expected). *Packaging is lint-checked; full build not yet run on Fedora.*
- Fedora package names were validated against the rpmlint spec parser and current Fedora
  knowledge but not confirmed against a live dnf repo (the dep-probe loop in `build-in-docker.sh`
  does that when run).
- `dbus-tools` is the modern Fedora package that provides `dbus-send`; on very old Fedora
  releases `dbus-send` shipped in the `dbus` package. Targeting current Fedora, `dbus-tools` is
  correct; the helpers degrade gracefully (`mx4-playpause` prefers `qdbus6` anyway).
- The `%check` section is intentionally omitted (the daemon's pytest is not run at package time);
  rpmlint flags this as a warning, not an error — acceptable for a hardware addon package.

---

## Cross-distro notes

- **No `v0.1.0` upstream git tag exists yet.** This is the single most important caveat and it
  affects every distro: Gentoo's versioned `0.1.0` ebuild `SRC_URI` 404s (use the `9999` live
  ebuild), Arch's default source is a local `git archive` tarball with `sha256sums=SKIP` (or use
  the `-git` AUR variant), and Debian/Fedora build from an in-tree tarball. Cutting and pushing
  a `v0.1.0` tag is the prerequisite for the versioned/release packaging paths.
- **`mx4-playpause` was the universal gap.** Every distro's packaging predated this helper and
  omitted it; it has now been added to all four (Gentoo `dobin`, Debian `rules`, Arch
  `package()`, Fedora `%install`/`%files`).
- **`qdbus6` preferred, `dbus-send` fallback.** `mx4-playpause` prefers `qdbus6`
  (`dev-qt/qttools:6` / `qdbus-qt6` / `qt6-tools` / `qt6-qttools`) and falls back to `dbus-send`
  (the always-present `dbus`/`dbus-bin`/`dbus-tools`). On Debian bookworm specifically, `qdbus6`
  is off-`PATH`, so the fallback is what actually runs there.
- **Daemon is per-user, never root**, on system Python with no venv. It is not enabled by
  default — start it via XDG autostart or `systemctl --user enable --now`. After install on any
  distro, re-plug the receiver once for udev uaccess and run `mx4-config`.
