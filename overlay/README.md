# mx4-radial — MX Master 4 radial menu overlay

A C++/Qt6 + QML radial ("pie") menu overlay for the MX Master 4 desktop addon.
It is the GUI half of the project (the haptic daemon lives in `../daemon/`); the
two talk over D-Bus, but the overlay also runs **fully standalone** in demo mode
with no daemon present.

Targets **KDE Plasma 6** (Wayland + X11) and **LXQt** (X11). Only depends on
**Qt6** and **LayerShellQt** — no KF6 — to keep the build small and green.

## Build

```bash
cmake -S overlay -B overlay/build -G Ninja
cmake --build overlay/build
```

Requirements: Qt6 (Core Gui Qml Quick DBus), LayerShellQt,
cmake ≥ 3.16, a C++17 compiler. `extra-cmake-modules` (ECM) is used for install
paths *if present*; otherwise it falls back to `GNUInstallDirs`, so ECM is
optional. If LayerShellQt is missing, the overlay still builds as an X11-only
binary (Wayland code is compiled out).

## Run

Standalone demo (shows the ring immediately, dismiss with Escape / click /
outside, then it exits — no daemon needed):

```bash
./overlay/build/mx4-radial --demo
```

Service mode (registers on D-Bus and waits for the daemon to summon it):

```bash
./overlay/build/mx4-radial            # owns dev.usidiamond.mx4.Overlay, waits for Show()
./overlay/build/mx4-radial --menu foo # default menu id when Show("") is called
```

`--menu <id>` sets the *default* menu id used when `Show("")` is invoked with an
empty argument (and for `--demo`). A non-empty `Show("<id>")` arg overrides it.
The id selects the config section: `default` → `[radial]`; any other id →
`[radial:<id>]`, falling back to `[radial]` then the built-in default.

## D-Bus interface

The overlay **exports**:

| | |
|---|---|
| bus name | `dev.usidiamond.mx4.Overlay` |
| object | `/dev/usidiamond/mx4/Overlay` |
| interface | `dev.usidiamond.mx4.Overlay` |
| methods | `Show(s menuId)`, `Hide()` |
| signal | `ActionChosen(s actionId)` |

The overlay owns its **own** name `dev.usidiamond.mx4.Overlay`, *distinct* from
the daemon's `dev.usidiamond.mx4`, so both processes co-run cleanly: the daemon
drives the overlay through this name, and the overlay calls the daemon for
haptics through the daemon's name (below).

The overlay **calls** the daemon for haptics (no-op if absent):

| | |
|---|---|
| bus name | `dev.usidiamond.mx4` |
| object | `/dev/usidiamond/mx4` |
| interface | `dev.usidiamond.mx4.Daemon` |
| method | `PlayHaptic(s waveform)` |

Waveforms used (all real firmware waveforms — see `docs/RESEARCH.md`):
`SUBTLE_COLLISION` on segment-hover change, `COMPLETED` on commit,
`DAMP_STATE_CHANGE` on cancel. Hover ticks are debounced (~40 ms) so the motor
is never machine-gunned. Daemon presence is tracked via a `QDBusServiceWatcher`,
so the hot path never blocks on a synchronous bus probe.

Trigger a show by hand:

```bash
qdbus6 dev.usidiamond.mx4.Overlay /dev/usidiamond/mx4/Overlay \
       dev.usidiamond.mx4.Overlay.Show default
```

## Config

Shared config file (same one the daemon / KCM write):
`~/.config/mx4desktop/config.ini`, `[radial]` section. All keys optional; with
no file you get a sensible built-in default whose **center action is the
auto-detected Task Manager**.

```ini
[radial]
center/label=Task Manager
center/icon=utilities-system-monitor
center/command=plasma-systemmonitor      ; quote-aware split, NO shell
count=6
1/id=launcher
1/label=Launcher
1/icon=system-run
1/command=krunner
2/id=lock
2/label=Lock
2/icon=system-lock-screen
2/command=loginctl lock-session
; ... up to <count>
```

Task-manager auto-detection order: `plasma-systemmonitor` → `ksysguard` →
`qps` → `lxtask` → `gnome-system-monitor` → `xterm -e htop` (first on `PATH`).

Action launching uses `QProcess` with an **argv list** (quote-aware split) —
there is **no shell**, so menu labels/commands cannot inject.

## Wayland vs X11 (honest note)

A normal Wayland client **cannot** read the global cursor position nor place a
surface at an absolute x,y, and `wlr-layer-shell` only centers a surface between
anchors. So:

- **Wayland / Plasma 6:** the overlay appears **center-screen** via LayerShellQt
  (layer `Overlay`, no anchors, exclusive-zone 0, keyboard `OnDemand` so Escape
  and arrow keys work — layer surfaces get no keyboard by default). This is
  expected and correct, not a bug.
- **X11 / LXQt (and Plasma-X11):** the overlay is a frameless `Qt::Tool` window
  placed **at the cursor** (X11 can query the pointer). Nicer UX, for free.

Cursor-anchoring on Wayland would require shipping a small C++ KWin effect
plugin (the Kando approach); that is deliberately out of scope for v1.

## Files

- `src/main.cpp` — app, arg parsing, D-Bus Overlay service, view lifecycle,
  theme-icon image provider.
- `src/RadialController.{h,cpp}` — QML-facing model + highlight/commit/cancel,
  haptic ticks, argv-safe launching.
- `src/DaemonHaptics.{h,cpp}` — QtDBus haptic client (graceful no-op + debounce).
- `src/MenuConfig.{h,cpp}` — INI loader + built-in default + task-mgr detection.
- `src/PlatformWindow.{h,cpp}` — Wayland LayerShellQt vs X11 cursor placement.
- `src/OverlayService.{h,cpp}` — D-Bus `Show`/`Hide`/`ActionChosen`.
- `qml/RadialMenu.qml`, `qml/Segment.qml` — the GPU-drawn ring (Shape +
  PathAngleArc), center hub, highlight, animations, pointer/keyboard input.
