# Architecture

Three cooperating pieces over a shared HID++ transport, plus thin per-desktop shims.
Designed to run on **KDE Plasma 6** (Wayland + X11) and **LXQt** (X11), with a
DE-agnostic core.

```
                         ┌──────────────────────────────────────┐
                         │            mx4 daemon                 │
                         │  (systemd user service, one process)  │
                         │                                       │
   /dev/hidrawN  ───────▶│  HidppTransport                       │
   (Bolt rx / BT)        │   • resolve device + feature indices  │
                         │   • play_waveform(idx)  fn 0x40       │
                         │   • set_level(0..100)   fn 0x20       │
                         │   • divert Haptic ctrl  (0x1B04)      │
                         │   • read diverted-control events ─────┼──┐ trigger
                         │                                       │  │
                         │  HapticEngine ◀── EventBus ◀── sources │  │
                         │                                       │  │
                         └───────┬───────────────────────┬───────┘  │
                                 │ D-Bus (own iface)      │          │
                  show/pick      ▼                        ▼          ▼
                         ┌───────────────┐        event sources   RadialController
                         │ Radial overlay│        (see below)     decides: show menu
                         │ Qt6/QML       │
                         │ • LayerShellQt│  Plasma/Wayland → center-screen
                         │ • frameless X │  LXQt/X11       → at cursor
                         └───────────────┘
                                 ▲
                                 │ reads config
                         ┌───────────────┐
                         │ Config (KConfig/INI) │  ← KCM (Plasma) or Qt window (LXQt)
                         └───────────────┘
```

## Components

### 1. `mx4d` — the daemon (core, DE-agnostic)
A long-lived process, shipped as a **systemd user service**
(`WantedBy=graphical-session.target`). Owns the HID++ connection and all policy.

- **HidppTransport** — opens the receiver/mouse `hidraw` node, runs the HID++ 2.0
  request/response + notification loop. On start it resolves the device index and the
  HAPTIC (`0x19B0`) / REPROG-CONTROLS (`0x1B04`) feature indices via the ROOT feature
  (`0x0000`) — no hardcoded indices. Reference packet format proven in
  `tools/haptic_test.py`.
- **HapticEngine** — the only thing that talks haptics. `play(waveform)` and
  `setLevel(0..100)`. Debounces/rate-limits so bursts of events don't machine-gun the
  motor. Respects a global enable + per-source intensity.
- **RadialController** — when the trigger fires, raises the overlay over D-Bus and
  feeds it the configured menu; ticks the haptic motor as the highlighted segment
  changes and on commit.
- **EventBus + sources** — pluggable producers of "something happened" events that map
  to haptic waveforms (see Ambient Haptics below).

### 2. Radial overlay — `mx4-radial` (C++/Qt6 + QML)
A separate GUI process the daemon shows/hides over D-Bus (kept separate so a UI crash
never drops the HID connection, and so it can hold a Wayland surface the daemon
shouldn't).

- **Plasma/Wayland:** frameless transparent **LayerShellQt** surface, `LayerOverlay`,
  window type `toolbar`, emptied input region except the menu hit-area, **center-screen**
  (Wayland can't place at the cursor). Optional cursor-anchoring later via a small C++
  KWin effect plugin (Kando pattern).
- **LXQt/X11 (and Plasma/X11):** plain frameless `Qt::Tool` window placed **at the
  cursor** (X11 lets us query the pointer) — the nicer UX, for free.
- Rendering: QML `Shape`/`PathArc` segments, snap-to-angle selection, segment
  highlight + scale. Each hovered segment requests a haptic tick from the daemon.

### 3. Config — `mx4ctl` / KCM
One config file (KConfig INI under `~/.config/mx4desktop/`). Two front-ends sharing it:
a Plasma **KCM** (System Settings page) and a plain Qt settings window for LXQt.

## Trigger model (how the menu is summoned)

1. **MX4 haptic panel (primary)** — daemon diverts the `Haptic` control via `0x1B04`;
   the panel's press arrives as an HID++ diverted-control notification → show menu.
   (Exact CID to be confirmed on hardware — see STATUS.md.)
2. **Global hotkey (fallback / non-MX4)** — KGlobalAccel on Plasma, GlobalShortcuts
   portal elsewhere. Always available so the feature degrades gracefully.

## Radial menu defaults

The default menu's **primary (center / first) action is the Task Manager / system
monitor**, auto-detected per environment:

| Environment | Launch |
|---|---|
| KDE Plasma | `plasma-systemmonitor` (fallback `ksysguard`) |
| LXQt | `qps` (fallback `lxtask`) |
| Generic | `gnome-system-monitor`, then `xterm -e htop` |

Other default slots (all user-editable): app launcher, switch virtual desktop,
play/pause media, lock screen, custom command. A press-and-release on the trigger with
no movement invokes the center action (Task Manager) directly.

## Ambient haptics (event → waveform)

The HapticEngine subscribes to an **EventBus** fed by pluggable sources. Each source
maps to a configurable waveform + intensity; everything is debounced and respects a
master enable and a quiet-hours option.

| Source | Mechanism (DE-agnostic where possible) | Default waveform |
|---|---|---|
| **Desktop notifications / alerts** | Monitor `org.freedesktop.Notifications` `Notify` on the session bus (works on Plasma **and** LXQt). Urgency 2 (critical) → stronger waveform. | `HAPPY_ALERT`; critical → `ANGRY_ALERT` |
| **Application focus change** | X11/LXQt: watch `_NET_ACTIVE_WINDOW` on the root window via XCB. Plasma/Wayland: tiny KWin script bridging `activeWindow` changes to our D-Bus iface (no portable Wayland signal exists). | `SUBTLE_COLLISION` |
| **System sounds** | Tap PipeWire/PulseAudio for new short-lived playback streams (event sounds). Stretch goal; v1 can fold "sounds" into the notifications source. | `KNOCK` |

This satisfies the requirement: **haptics respond to system noises, desktop alerts,
and application-change events.** v1 lands notifications + focus-change (both
portable); the PipeWire sound tap follows.

## Tech stack decision

- **Language/toolkit:** C++/Qt6 + QML for daemon and overlay (only stack strong on
  *both* raw HID/HID++ and a real Plasma-6 Wayland layer-shell overlay; LayerShellQt
  has no Python binding). hidapi (hidraw backend) for HID I/O. D-Bus (Qt DBus) between
  daemon, overlay, and KWin shim.
- **Rapid-prototype escape hatch:** a Python build of the daemon (reusing Solaar's
  `logitech_receiver` + `python-evdev`) is acceptable for early iteration, but the
  **overlay stays C++/Qt6** regardless. `tools/haptic_test.py` is the seed of the
  Python path and the reference for the HID++ packet format.
- **Build/packaging:** CMake + extra-cmake-modules; systemd user unit; Plasma
  `metadata.json` for the KCM/KWin script; distro package or Flatpak for distribution.

## Out of scope (v1)

- Driving the mouse's *internal* on-device Actions Ring (undecoded; needs Windows USB
  capture). We render our own overlay instead.
- Custom/arbitrary haptic waveforms (firmware exposes only 16 pre-baked + global level).
