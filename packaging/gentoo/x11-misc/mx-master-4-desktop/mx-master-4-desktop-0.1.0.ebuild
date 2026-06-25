# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

# Daemon (mx4d) runs on a single system Python interpreter; no venv/pip at
# runtime. The C++ overlay + config GUI are built with CMake. Two independent
# CMake projects (overlay/ and config-ui/) live in this repo with no umbrella
# CMakeLists.txt, so the cmake-eclass phases are driven once per sub-project.
PYTHON_COMPAT=( python3_{11..14} )

inherit cmake python-single-r1 systemd udev xdg

DESCRIPTION="Actions Ring radial overlay + native haptics daemon for the Logitech MX Master 4"
HOMEPAGE="https://github.com/UsiDiamond/mx-master-4-desktop"
SRC_URI="https://github.com/UsiDiamond/${PN}/archive/refs/tags/v${PV}.tar.gz -> ${P}.tar.gz"

LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64 ~arm64"
# systemd: install the systemd user units. Default (off) uses the portable XDG
# autostart entry, which is what OpenRC / runit / s6 sessions rely on.
IUSE="+sound systemd"

REQUIRED_USE="${PYTHON_REQUIRED_USE}"

# Runtime:
#  - daemon: the chosen Python plus dbus-python, PyGObject (gi), python-xlib,
#    all imported from the SYSTEM site-packages.
#  - overlay + config GUI: Qt6 base (with dbus, which is default-on) and
#    qtdeclarative (Quick / QML / QuickControls2), plus LayerShellQt for the
#    Wayland layer-shell surface.
#  - udev rule provides the uaccess hidraw ACL for the Logitech receiver.
RDEPEND="
	${PYTHON_DEPS}
	$(python_gen_cond_dep '
		dev-python/dbus-python[${PYTHON_USEDEP}]
		dev-python/pygobject:3[${PYTHON_USEDEP}]
		dev-python/python-xlib[${PYTHON_USEDEP}]
	')
	dev-qt/qtbase:6[dbus,gui]
	dev-qt/qtdeclarative:6
	kde-plasma/layer-shell-qt:6
	virtual/udev
"
# extra-cmake-modules is OPTIONAL for the build (CMake falls back to
# GNUInstallDirs), but pulling it in lands the binaries in the same prefixes a
# Plasma install expects and exercises the ECM path; cheap, so we depend on it.
DEPEND="${RDEPEND}"
BDEPEND="
	${PYTHON_DEPS}
	dev-build/cmake
	kde-frameworks/extra-cmake-modules
"

# Optional ambient "system sound" haptic source needs a runtime monitor for
# either PulseAudio (pactl) or PipeWire (pw-mon). Each missing one just disables
# that source, so this is a soft, USE-gated recommendation, not a hard dep.
PDEPEND="
	sound? (
		|| (
			media-sound/pulseaudio-daemon
			media-video/pipewire
		)
	)
"

# The two CMake sub-projects, relative to ${S}.
MX4_CMAKE_DIRS=( overlay config-ui )

pkg_setup() {
	python-single-r1_pkg_setup
}

src_prepare() {
	# cmake_src_prepare insists on a CMakeLists.txt under CMAKE_USE_DIR; this
	# repo has none at the top level (two independent sub-projects), so point it
	# at the first one. Prepare is project-agnostic here (applies PATCHES +
	# eapply_user, then runs the eclass's in-source bookkeeping).
	local CMAKE_USE_DIR="${S}/${MX4_CMAKE_DIRS[0]}"
	cmake_src_prepare
}

src_configure() {
	local d
	for d in "${MX4_CMAKE_DIRS[@]}"; do
		local CMAKE_USE_DIR="${S}/${d}"
		local BUILD_DIR="${WORKDIR}/${d}_build"
		local mycmakeargs=(
			-DCMAKE_INSTALL_PREFIX="${EPREFIX}/usr"
		)
		cmake_src_configure
	done
}

src_compile() {
	local d
	for d in "${MX4_CMAKE_DIRS[@]}"; do
		local CMAKE_USE_DIR="${S}/${d}"
		local BUILD_DIR="${WORKDIR}/${d}_build"
		cmake_src_compile
	done
}

src_install() {
	# Where the staged daemon package lives; the launcher points PYTHONPATH
	# here. get_libdir() is only valid inside a phase, not global scope.
	local MX4_LIBDIR="/usr/$(get_libdir)/${PN}"

	# --- C++ overlay + config GUI (mx4-radial, mx4-config, .desktop) ---------
	local d
	for d in "${MX4_CMAKE_DIRS[@]}"; do
		local CMAKE_USE_DIR="${S}/${d}"
		local BUILD_DIR="${WORKDIR}/${d}_build"
		cmake_src_install
	done

	# --- daemon: stage the mx4d package onto the system Python --------------
	# No venv, no pip. We install the package tree into a private libdir and
	# generate a launcher that runs `python -m mx4d` with PYTHONPATH set, which
	# matches install.sh's runtime contract exactly.
	insinto "${MX4_LIBDIR}"
	doins -r "${S}/daemon/mx4d"
	# Strip any stray build caches that slipped into the tarball.
	rm -rf "${ED}${MX4_LIBDIR}/mx4d/__pycache__" || die
	find "${ED}${MX4_LIBDIR}/mx4d" -name '*.pyc' -delete || die

	# Launcher -> /usr/bin/mx4d. Uses the resolved single interpreter.
	cat > "${T}/mx4d" <<-EOF || die
		#!/usr/bin/env bash
		# mx4d launcher (system python, no venv/pip). PYTHONPATH points at the
		# package staged by the mx-master-4-desktop ebuild.
		export PYTHONPATH="${EPREFIX}${MX4_LIBDIR}\${PYTHONPATH:+:\$PYTHONPATH}"
		exec "${EPREFIX}/usr/bin/${EPYTHON}" -m mx4d "\$@"
	EOF
	dobin "${T}/mx4d"

	# --- udev rule (uaccess hidraw ACL; the one privileged bit) ------------
	udev_dorules "${S}/packaging/udev/70-mx-master-4.rules"

	# --- portable XDG autostart (PRIMARY on every init; daemon only) --------
	# Exec=mx4d is already on PATH (/usr/bin) for a system package, so ship the
	# entry verbatim into /etc/xdg/autostart. Only the daemon autostarts; it
	# lazy-launches the overlay.
	insinto /etc/xdg/autostart
	doins "${S}/packaging/autostart/mx4desktop.desktop"

	# --- systemd user units (USE=systemd only) -----------------------------
	if use systemd; then
		systemd_douserunit "${S}/packaging/systemd/mx4desktop.service"
		systemd_douserunit "${S}/packaging/systemd/mx4-overlay.service"
	fi

	# --- KWin focus-bridge: shipped as DATA only, never enabled ------------
	# Plasma-Wayland-only at runtime; gated by XDG_CURRENT_DESKTOP at session
	# time, NOT by a hard Plasma dependency. EnabledByDefault=false in its
	# metadata.json keeps it inert until the user opts in.
	insinto /usr/share/kwin/scripts/mx4-focus-bridge
	doins "${S}/packaging/kwin/metadata.json"
	insinto /usr/share/kwin/scripts/mx4-focus-bridge/contents/code
	doins "${S}/packaging/kwin/contents/code/main.js"

	# --- Solaar helper files (opt-in data; user runs setup manually) -------
	insinto /usr/share/${PN}/solaar
	doins "${S}/packaging/solaar/mx4-rules.yaml"
	doins "${S}/packaging/solaar/README.md"
	exeinto /usr/share/${PN}/solaar
	doexe "${S}/packaging/solaar/setup-solaar.sh"

	# --- docs --------------------------------------------------------------
	dodoc README.md
	[[ -f docs/INSTALL.md ]] && dodoc docs/INSTALL.md
}

pkg_postinst() {
	udev_reload

	elog "The mx4d daemon runs on the system ${EPYTHON} (no venv/pip)."
	elog "It autostarts via /etc/xdg/autostart/mx4desktop.desktop on login;"
	elog "the daemon lazy-launches the mx4-radial overlay on demand."
	elog
	elog "First run creates ~/.config/mx4desktop/config.ini; an existing config"
	elog "is never overwritten."
	elog
	if use systemd; then
		elog "systemd user units were installed. To start now / enable on login:"
		elog "    systemctl --user enable --now mx4desktop.service mx4-overlay.service"
	else
		elog "No systemd units (USE=-systemd). On OpenRC/runit/s6 the XDG autostart"
		elog "entry covers login. To run ad hoc:"
		elog "    mx4d --verbose &"
		elog "    pkill -TERM -f 'python.* -m mx4d'"
	fi
	elog
	elog "KWin focus-bridge (Plasma-Wayland only, opt-in) was shipped to"
	elog "  /usr/share/kwin/scripts/mx4-focus-bridge"
	elog "It is NOT enabled. On Plasma you can enable it via System Settings >"
	elog "Window Management > KWin Scripts. On X11/LXQt it is unnecessary."
}

pkg_postrm() {
	udev_reload
}
