# STATUS — read first when resuming

Project: bring the MX Master 4 **Actions Ring** + **native haptics** to Linux on
**KDE Plasma 6** and **LXQt**. Repo is private under the UsiDiamond GitHub account.

Last updated: **2026-06-24** (foundational scaffolding; prepared for a system restart).

## Where things stand

| Area | State |
|---|---|
| Repo + license + docs | **Done** — this repo, MIT, README + RESEARCH + ARCHITECTURE |
| Device identified (real hw) | **Done** — MX Master 4, `046d:B042`, HID++ 4.5, Bolt rx `046d:C548`, device index 2, `/dev/hidraw11`, battery 55% |
| **Fire haptics from Linux** | **PROVEN** — `tools/haptic_test.py` writes raw HID++ `0x19B0`/fn `0x40` to hidraw, exit 0, no root (session ACL). Feature index `0x0B` on this device |
| Haptic intensity | Known — fn `0x20`, 0–100 (`haptic-level` reads 60) |
| Actions Ring trigger | Mechanism known — divert `Haptic` control via `0x1B04`; **exact CID byte unconfirmed** (see next steps) |
| Daemon `mx4d` | Not started |
| Radial overlay | Not started |
| Ambient-haptics sources | Not started (design done: notifications + focus-change + sounds) |
| Config / KCM | Not started |

## Decisions locked in (from the user)

1. Targets **both KDE Plasma 6 and LXQt** (X11 makes LXQt the easier overlay path).
2. Default radial action = **Task Manager / system monitor** (center/first slot;
   auto-detect `plasma-systemmonitor` / `qps` / fallback).
3. **Ambient haptics**: the mouse buzzes for **desktop notifications, system sounds,
   and application-focus changes** (configurable waveform per event).
4. Render **our own** overlay (Kando/JuhRadial style); do **not** reverse the mouse's
   internal on-device ring in v1.
5. Stack: **C++/Qt6 + QML + hidapi**; overlay must be C++ (no LayerShellQt Python
   binding). Python OK only for early daemon prototyping.

## Next steps (in order) — RESUME HERE

1. **[2-min hardware check] Confirm the Actions Ring CID.** With the mouse on:
   ```bash
   solaar config 'MX Master 4' divert-keys Haptic Diverted   # or set via 0x1B04
   solaar -dd 2>&1 | grep -i 'divert'   # then click the haptic panel
   ```
   Record the `diverted controls pressed: 0x…` byte → that's the trigger CID. Likely
   `0x1A0`/action `0x0109`. Note it in this file. Remember to set it back to `Regular`.
2. **Scaffold the CMake/ECM project** (`mx4d` daemon target, `mx4-radial` overlay
   target, shared `libmx4hidpp`). Stub D-Bus interface.
3. **Port the haptic path to C++** (hidapi): runtime feature-index resolution via ROOT
   `0x0000`, `play_waveform`, `set_level`, capability bitmask check.
4. **NotificationsSource** (monitor `org.freedesktop.Notifications`) → first ambient
   haptic. Most portable, gives an immediate visible/feelable win on both DEs.
5. **Trigger capture** (divert via `0x1B04`, read notifications) → fire a stub "menu
   open" haptic.
6. **Radial overlay v1** — center-screen LayerShellQt on Wayland; cursor-anchored
   Qt::Tool on X11. Default menu with Task Manager center action.
7. **Focus-change source** (X11 `_NET_ACTIVE_WINDOW`; KWin-script bridge on Wayland).
8. **Config + KCM**, packaging (systemd user unit), then PipeWire sound source.

## Gotchas already discovered (don't relearn these)

- Solaar **CLI** `haptic-play` is broken (`TypeError: Unable to marshal str as an
  array`). Don't depend on it — send the packet directly. The feature itself is fine.
- Feature **index** (`0x0B`) is per-device; resolve at runtime, don't hardcode outside
  the smoke test.
- Wayland: no global cursor pos, no absolute placement → center-screen overlay unless
  you ship a C++ KWin plugin. X11/LXQt has neither limit.
- Overlay must use KWin window type `toolbar` (not `dock`) or it gets no keyboard.
- `/dev/hidraw11` is accessible to the active-session user via a udev **ACL** (the `+`
  in `crw-rw----+`); not `plugdev` membership. A shipped install needs its own udev
  rule for robustness.

## Local checkout

`/home/magus/GitHub/mx-master-4-desktop` (on the primary dev box). Remote:
`UsiDiamond/mx-master-4-desktop` (private).
