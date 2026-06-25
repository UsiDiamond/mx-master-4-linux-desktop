# STATUS — read first when resuming

Project: bring the MX Master 4 **Actions Ring** + **native haptics** to Linux on
**KDE Plasma 6** and **LXQt**. Private repo under the UsiDiamond GitHub account.

Last updated: **2026-06-24** (Phases 1 & 2 complete + committed; Phase 3 integration next).

## Where things stand

| Area | State |
|---|---|
| Repo + license + docs | **Done** |
| Device identified (real hw) | **Done** — MX Master 4, `046d:B042`, HID++ 4.5, Bolt rx, device index 2. NOTE: hidraw node number is volatile across reboots/reconnects (seen as `hidraw11` then `hidraw7`); the daemon auto-detects, so don't rely on a fixed node |
| **Phase 1 — daemon** (`daemon/`, Python) | **DONE + committed** (`9a72aa1`). Standalone raw-HID++, no Solaar dep. Verified on hardware: selftest buzzes; `notify-send`→haptic; D-Bus `PlayHaptic`/`SetLevel`; trigger divert+restore clean; 36 unit tests pass |
| **Phase 2 — overlay** (`overlay/`, C++/Qt6) | **DONE + committed** (`640422d`). Builds clean vs Qt6 6.11 + LayerShellQt; `--demo` renders the ring on the live Plasma 6 Wayland session (screenshot-verified) + X11 cursor path |
| **Phase 3 — integration + packaging** | **NEXT** (see below) |
| Config UI / KCM | Not started (Phase 4) |

## Firmware capability finding (important, real)

This MX Master 4 unit's HAPTIC (`0x19B0`) capability mask (fn `0x00`) = **`0x0001003C`**.
Only these waveforms are supported: **SHARP_COLLISION, DAMP_COLLISION, SUBTLE_COLLISION,
HAPPY_ALERT, and an undocumented `0x10`**. **`COMPLETED` (0x07), WAVE, JINGLE, etc. are
NOT supported** — firmware silently ignores a play of an unsupported waveform. The daemon
gates every play on this mask and falls back to the nearest supported waveform. Any code
that fires haptics MUST check the mask, not assume the full 16-waveform table.

## D-Bus contracts (as built)

| Process | Bus name | Object path | Interface / members |
|---|---|---|---|
| Daemon | `dev.usidiamond.mx4` | `/dev/usidiamond/mx4` | `dev.usidiamond.mx4.Daemon`: `PlayHaptic(s)->b`, `SetLevel(i)->b`; signals `TriggerPressed()`, `TriggerReleased()` |
| Overlay | `dev.usidiamond.mx4.Overlay` | `/dev/usidiamond/mx4/Overlay` | `dev.usidiamond.mx4.Overlay`: `Show(s menuId)`, `Hide()`; signal `ActionChosen(s)` |

(Distinct bus names so daemon + overlay co-run.) Overlay calls `Daemon.PlayHaptic` on
hover/commit (graceful no-op if daemon absent). In `--demo` the overlay does not register
its service (stays standalone).

## Next steps — Phase 3 (integration + packaging) — RESUME HERE

1. **Wire daemon → overlay**: on `TriggerPressed` (Actions Ring panel), the daemon ensures
   the overlay is running and calls `Overlay.Show(menuId)`. Lifecycle decision: run the
   overlay as a second always-on (hidden) systemd user service, shown on demand.
2. **Packaging**: top-level installer (install.sh or CMake superproject) — daemon (venv or
   `~/.local`), overlay binary, **two systemd user units** (`mx4desktop.service` daemon +
   `mx4-overlay.service` overlay), a **udev rule** granting hidraw access (robust beyond the
   session ACL), and a default config.
3. **End-to-end test**: daemon `ShowMenu` path → overlay shows → select center → launches
   the task manager (`plasma-systemmonitor`), with haptic ticks. (Physical panel tap remains
   the one manual verification — `parse_pressed_cids` is unit-tested against synthetic
   `divertedButtonsEvent` reports; divert/restore is hardware-confirmed.)
4. **Phase 4 (later)**: config GUI — a portable Qt/QML settings window (Plasma + LXQt) and/or
   a Plasma KCM, editing `~/.config/mx4desktop/config.ini`. Plus the native-Wayland focus
   KWin-script bridge.

## Gotchas already discovered (don't relearn)

- Firmware capability mask gates waveforms (see above). `COMPLETED` is unsupported here.
- hidraw node number is volatile — auto-detect; `tools/haptic_test.py` honors `MX4_HIDRAW`.
- `BecomeMonitor` for notifications MUST run on a **private** D-Bus connection, or it turns
  the shared session connection into a receive-only monitor and destroys the daemon's own
  bus name.
- All blocking HID I/O must be off the GLib mainloop thread (use the daemon's worker queue),
  or notification dispatch stalls and `set_level` times out.
- Solaar CLI `haptic-play` is broken (marshal TypeError) — irrelevant, we send packets raw.
- Wayland: overlay is center-screen (no cursor anchoring without a KWin effect plugin);
  X11/LXQt anchors at the cursor.
- Overlay must use KWin window type `toolbar` (not `dock`) or it gets no keyboard.

## Local checkout

`/home/magus/GitHub/mx-master-4-desktop`. Remote `UsiDiamond/mx-master-4-desktop` (private).
Commits: `0e2e565` scaffold, `640422d` overlay, `9a72aa1` daemon.
