# mx4-config — MX Master 4 settings GUI

A portable **C++/Qt6 + QML** settings window for the MX Master 4 Linux Desktop addon.
It edits the **shared INI** the daemon and the overlay both read/write
(`~/.config/mx4desktop/config.ini`, honouring `XDG_CONFIG_HOME`), and live-previews
waveforms through the running daemon.

Built on plain **QtQuick Controls 2** — **no KF6 dependency** — so it runs on
**KDE Plasma 6** *and* **LXQt** (and anywhere Qt6 is present).

## What it edits

| Section | Keys written (exactly as the daemon / overlay parse them) |
|---|---|
| `[ambient]` | `enabled`, `quiet_hours` (`true`/`false`), `debounce_interval` (float), `haptic_level` (0..100, GUI-owned) |
| `[source:notification]` / `[source:focus]` / `[source:sound]` | `enabled`, `waveform` (name), `intensity` (0..100) |
| `[trigger]` | `divert_panel` (tri-state `auto`/`true`/`false`), `waveform` (name) |
| `[radial]` | `center/command` (argv, quote-aware, **no shell**), `center/label`, `center/icon`, `default_menu`, `count`, and per-segment `<n>/id`, `<n>/label`, `<n>/icon`, `<n>/command` |
| `[overlay]` | `command` (how the daemon lazily launches the overlay) |

The file is emitted in **configparser-compatible** form — literal `[source:focus]`
section names and literal `/` key separators — because the Python daemon reads it
with `configparser` while the overlay reads it with `QSettings`. (A naïve
`QSettings`-written file would escape `:` → `%3A` and use `\` separators, which the
daemon could not parse; the GUI writes the INI by hand to avoid that.) Unknown
sections/keys are **preserved** across a save.

## UI

- **Ambient haptics** — master enable, quiet-hours, debounce slider, and per-source
  rows (enable + waveform combo + intensity slider) for notification / focus / sound.
- **Haptics** — a global level slider, pushed live to the device via `Daemon.SetLevel`.
- **Actions Ring trigger** — divert-panel toggle and the press waveform.
- **Radial menu** — the center action (label / icon / command / default menu id) and a
  full **segment list editor**: add / remove / reorder (↑ ↓), each with label, id, icon,
  action type (`command` / `noop`) and command.
- **Overlay** — the daemon's lazy-launch command.

Every waveform combo has a **Test** button that calls `Daemon.PlayHaptic(name)` so you
feel the buzz immediately. When the daemon is running its **capability mask** is read
(`Daemon.GetCapabilities`) and unsupported waveforms are marked *"(not on this device)"*;
when the daemon is absent everything is shown with a *"daemon not running"* hint and Test
is a graceful no-op.

A dirty-state drives **Apply** / **Revert**, with a save-on-close prompt.

## Build

```bash
cmake -S config-ui -B config-ui/build -G Ninja
cmake --build config-ui/build
```

Requirements: Qt6 (Core Gui Qml Quick QuickControls2 DBus), CMake ≥ 3.16, a C++17
compiler. ECM is used for install paths *if present*, else `GNUInstallDirs`.
QuickControls2 is verified at configure time; if its CMake package is split out on
your distro the build still proceeds and relies on the runtime QML import.

## Run

```bash
./config-ui/build/mx4-config
```

Or install it (`packaging/install.sh` builds and drops `mx4-config` plus a
`mx4-config.desktop` launcher into `~/.local/`), then launch **"MX Master 4 Settings"**
from the application menu.

## D-Bus (the daemon side it talks to)

| | |
|---|---|
| bus name | `dev.usidiamond.mx4` |
| object | `/dev/usidiamond/mx4` |
| interface | `dev.usidiamond.mx4.Daemon` |
| methods used | `PlayHaptic(s)->b` (preview), `SetLevel(i)->b` (live level), `GetCapabilities()->u` (waveform mask) |

All calls are graceful no-ops when the daemon is not on the bus; presence is tracked
with a `QDBusServiceWatcher` so the UI updates as the daemon appears / leaves.

## Files

- `src/main.cpp` — app, QML engine, style fallback (Fusion on non-Plasma), backend wiring.
- `src/ConfigModel.{h,cpp}` — the working-copy model + the configparser-compatible
  INI reader/writer (load / save / revert / dirty; segment + source editing).
- `src/DaemonBridge.{h,cpp}` — QtDBus client for PlayHaptic / SetLevel / GetCapabilities
  and the supported-waveform marking.
- `qml/Main.qml` — the settings window (all sections + footer).
- `qml/SectionFrame.qml` — a titled card grouping form rows.
- `qml/WaveformPicker.qml` — waveform combo + Test button (support-marked).
