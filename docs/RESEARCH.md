# Research notes — MX Master 4 on Linux (haptics, Actions Ring, KDE/LXQt overlay)

Consolidated from device probing on real hardware (2026-06-24) plus a literature
sweep of Solaar, libratbag, Kando, and community reverse-engineering. Load-bearing
facts are cited. This is the technical ground truth the implementation stands on.

---

## 1. The device (verified live with `solaar show`)

| Fact | Value |
|---|---|
| Model | Logitech MX Master 4 |
| Vendor / Product ID | `046d` / **`B042`** (same for BLE and 2.4 GHz Bolt) |
| Model ID | `B04200000000` |
| HID++ version | **4.5** (internal version of the HID++ 2.0 family — not a new protocol) |
| Link | Logi Bolt receiver `046d:C548` (a *shared* dongle; not MX4-specific) |
| Device index on receiver | **2** |
| hidraw node (this machine) | `/dev/hidraw11` (the receiver) |
| Battery feature | `UNIFIED BATTERY {1004}` |
| Reports | `0x10` short (7 bytes), `0x11` long (20 bytes) |

`solaar` ≥ 1.1.17 recognizes the device; this machine runs 1.1.19. libratbag also
has a device file (`logitech-MX-Master-4.device`, matches the **Bluetooth** path).

### HID++ 2.0 features exposed (46 total; the ones that matter)

| Idx | Feature | ID | Use to us |
|----:|---|---|---|
| 9 | UNIFIED BATTERY | `1004` | battery level for UI |
| **11** | **HAPTIC** | **`19B0`** | **fire haptic waveforms** |
| 12 | FORCE SENSING BUTTON | `19C0` | force threshold of the panel button |
| **13** | **REPROG CONTROLS V4** | **`1B04`** | **divert + capture the Actions Ring trigger** |
| 14/15 | CHANGE HOST / HOSTS INFO | `1814`/`1815` | Easy-Switch state |
| 17 | SMART SHIFT ENHANCED | `2111` | wheel ratchet |
| 18 | HIRES WHEEL | `2121` | scroll |

> The feature **index** (left column) is this device's table position and is what
> goes on the wire. It is discovered at runtime via the ROOT feature (`0x0000`) on a
> real device — never hardcode it except in throwaway smoke tests.

---

## 2. Haptics — SOLVED (feature `0x19B0`)

Reverse-engineered and merged into mainline Solaar (PR
[#3024](https://github.com/pwr-Solaar/Solaar/pull/3024)). Functions:

| Fn | Purpose | Params |
|---|---|---|
| `0x00` | get capabilities | reply bytes 4–8 = supported-waveform bitmask; check `(1<<i) & mask` before playing waveform `i` |
| `0x10` | read level/state | `[0]&1`=enabled, `[1]`=level, `[2]&1`="4 discrete levels only" |
| `0x20` | write level | `b"\x01"+level` (0–100) to enable; `b"\x00\x32"` to disable |
| **`0x40`** | **play a waveform** | one byte = waveform index |

### Waveform index table (verified against Solaar `HapticWaveForms`)

```
0x00 SHARP_STATE_CHANGE   0x05 HAPPY_ALERT   0x0A FIREWORK
0x01 DAMP_STATE_CHANGE    0x06 ANGRY_ALERT   0x0B MAD
0x02 SHARP_COLLISION      0x07 COMPLETED     0x0C KNOCK
0x03 DAMP_COLLISION       0x08 SQUARE        0x0D JINGLE
0x04 SUBTLE_COLLISION     0x09 WAVE          0x0E RINGING
                                             0x1B WHISPER_COLLISION
```

Indices are sparse (jumps from `0x0E` to `0x1B`) and gated by the fn-`0x00` bitmask.

> **Real finding (test unit, 2026-06-24):** the capability mask read back as
> `0x0001003C` — i.e. only `SHARP_COLLISION`, `DAMP_COLLISION`, `SUBTLE_COLLISION`,
> `HAPPY_ALERT`, and an undocumented bit `0x10` are supported. `COMPLETED` (0x07),
> `WAVE`, `JINGLE`, etc. are **silently ignored** by firmware when played. Always
> read the mask and gate (or fall back to a supported waveform) — never assume the
> full 16-entry table. The daemon does this; `tools/haptic_test.py` does not (raw).

### On-wire "play waveform" report (PROVEN on this machine)

```
0x10  0x02  0x0B  0x4E  <wf>  0x00  0x00
 │     │     │     │     └ waveform index
 │     │     │     └ fn 0x40 ("play") already shifted into the high nibble | sw-id 0x0E
 │     │     └ feature index of 0x19B0 (0x0B here; resolve at runtime)
 │     └ device index (2)
 └ short report id
```

`tools/haptic_test.py` writes exactly this and runs with exit 0 against
`/dev/hidraw11`. Logitech's public HID++ docs do **not** document `0x19B0` — this is
reverse-engineered. There is **no evidence** of custom-waveform upload or arbitrary
per-pulse intensity; you get the 16 pre-baked waveforms + a global 0–100 level.

The Solaar **CLI** path (`solaar config … haptic-play NAME`) is currently **broken**
(`TypeError: Unable to marshal str as an array`) — a Solaar bug, not ours. We send the
packet ourselves and avoid it.

---

## 3. Actions Ring trigger — capturable, exact CID needs a 2-minute hardware check

The MX4's headline button is the **haptic touch panel** ("Haptic Sense Panel"); on
Windows, clicking it opens the Actions Ring. On this device it surfaces in
`REPROG CONTROLS V4 {1B04}` as a control literally named **`Haptic`**, whose default
action is **`unknown:0109`**:

```
Key/Button Actions: { …, Mouse Gesture Button:Gesture Button, Haptic:unknown:0109 }
Key/Button Diversion: { …, Haptic:Regular }
```

**How we capture it:** set that control's diversion to *Diverted* via `0x1B04`. A
diverted control stops doing its default action and instead emits an HID++
notification carrying its Control ID (CID); the control then becomes invisible to
evdev (this is expected). We read that notification off the same hidraw node.

- Solaar exposes this as the `divert-keys` setting; the daemon will set it directly
  via `0x1B04` so it works without Solaar running.
- **Open item:** confirm the CID byte the panel emits. Run `solaar -dd`, divert the
  `Haptic` control, click the panel, and read the `diverted controls pressed: 0x…`
  notification. The daemon uses CID `0x01A0` / action `0x0109`
  (`ACTIONS_RING_CID` in `daemon/mx4d/trigger.py`); the divert + restore are
  hardware-confirmed, the exact press decode is the one remaining manual check.

> We render **our own** radial overlay (like JuhRadial / Kando) triggered by this
> button — we do **not** try to drive the mouse's internal on-device ring (that part
> is undecoded and would need Windows USB capture; out of scope for v1).

Refs: Solaar issues
[#2989](https://github.com/pwr-Solaar/Solaar/issues/2989),
[#3046](https://github.com/pwr-Solaar/Solaar/issues/3046),
[#2964](https://github.com/pwr-Solaar/Solaar/issues/2964);
[Solaar rules docs](https://pwr-solaar.github.io/Solaar/rules/).

---

## 4. Overlay on Wayland (Plasma) vs X11 (LXQt) — the hard constraints

Verified against Wayland/KWin docs and shipped code (Kando, koverlay, Gnome-Pie):

1. A normal Wayland client **cannot** read the global cursor position, and **cannot**
   place a surface at an absolute x,y. `wlr-layer-shell` only **centers** a surface
   between anchors. → **Plasma/Wayland default UX is a center-screen overlay.** True
   cursor-anchoring needs a small **C++ KWin effect plugin** exposing `workspace.cursorPos`
   over D-Bus (this is exactly why [Kando](https://github.com/kando-menu/kando) ships one).
2. **X11 (LXQt)** has none of these limits — you can query the pointer and place a
   frameless window at the cursor directly. So **LXQt support is strictly easier** and
   gives us cursor-anchored menus for free.
3. `Qt::WindowStaysOnTopHint` is **not honored** on KWin/Wayland → use LayerShellQt
   `LayerOverlay`. Click-through needs both `WindowTransparentForInput` **and** an
   emptied `wl_surface` input region (proven by [koverlay](https://github.com/erik96/koverlay)).
4. KWin window **type** matters: a layer/overlay must use type `toolbar` (not `dock`)
   or it receives **no keyboard events** (Escape-to-dismiss breaks).
5. No maintained Python binding for LayerShellQt exists → the overlay should be
   **C++/Qt6 + QML**.

### Triggers / input
- **Global hotkey:** KGlobalAccel (KF6) for a native Plasma addon; the freedesktop
  GlobalShortcuts portal for sandboxed/cross-DE.
- **Raw extra mouse button:** not bindable as a hotkey; capture via **evdev**
  (needs `input` group / udev) or — for the MX4 — via **HID++ diversion** (cleanest,
  no evdev grab). KWin scripts cannot bind mouse buttons.

### Prior art worth copying
- **Kando** (MIT) — the blueprint for a pie menu on Plasma 6 Wayland: thin C++ KWin
  effect plugin for cursor/focus over D-Bus + GlobalShortcuts portal trigger.
- **JuhRadial-mx** — PyQt6 radial overlay that talks HID++ over hidraw and already
  targets Plasma 6, GNOME, Hyprland, COSMIC, Sway, X11. Closest existing thing.
- **koverlay** — working Plasma 6 Qt6/QML/LayerShellQt transparent overlay.
- **mx4notifications** / **mx4-haptic-linux** — notification→haptic, DE-agnostic.

---

## 5. Packaging (Plasma 6 / general)

- Compiled C++ components (daemon, overlay, optional KWin plugin, KCM) ship via
  **CMake + extra-cmake-modules**; distribute as a distro package / Flatpak.
- Background process → **systemd user service** (`WantedBy=graphical-session.target`
  to stay DE-agnostic across Plasma and LXQt), not KDED, not bare autostart.
- Config UI → a System Settings **KCM** on Plasma; a plain Qt settings window on LXQt;
  both read/write the same config file.
- Plasma metadata is `metadata.json` with `"X-Plasma-API-Minimum-Version": "6.0"`.

---

## Known vs unknown (honest)

| Capability | Status |
|---|---|
| Talk to the device / identify it | **Known** (`046d:B042`, HID++ 2.0) |
| Fire haptics | **PROVEN** (raw packet, exit 0 on real hw) |
| Set haptic intensity | **Known** (fn `0x20`, 0–100) |
| Capture Actions Ring trigger in software | **Known mechanism** (divert `0x1B04`); exact CID byte = 2-min hardware check |
| Render our own radial overlay | **Known** (LayerShellQt center on Wayland; cursor-anchored on X11) |
| Cursor-anchored overlay on Plasma Wayland | **Known but needs** a C++ KWin plugin (Kando pattern) |
| Drive the mouse's *native* on-device ring | **Unsolved / out of scope** (needs Windows USB capture) |
| Custom/arbitrary haptic waveforms | **Not supported by firmware** (16 pre-baked only) |
