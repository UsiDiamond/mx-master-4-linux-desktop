# STATUS — read first when resuming

Project: bring the MX Master 4 **Actions Ring** + **native haptics** to Linux on
**KDE Plasma 6** and **LXQt**. Private repo under the UsiDiamond GitHub account.

Last updated: **2026-06-24** (Phases 1, 2 & 3 complete; Phase 3 integration +
packaging proven end-to-end on real hardware. Phase 4 = config GUI/KCM next).

## Where things stand

| Area | State |
|---|---|
| Repo + license + docs | **Done** |
| Device identified (real hw) | **Done** — MX Master 4, `046d:B042`, HID++ 4.5, Bolt rx, device index 2. NOTE: hidraw node number is volatile across reboots/reconnects (seen as `hidraw11` then `hidraw7`); the daemon auto-detects, so don't rely on a fixed node |
| **Phase 1 — daemon** (`daemon/`, Python) | **DONE + committed** (`9a72aa1`). Standalone raw-HID++, no Solaar dep. Verified on hardware: selftest buzzes; `notify-send`→haptic; D-Bus `PlayHaptic`/`SetLevel`; trigger divert+restore clean; 36 unit tests pass |
| **Phase 2 — overlay** (`overlay/`, C++/Qt6) | **DONE + committed** (`640422d`). Builds clean vs Qt6 6.11 + LayerShellQt; `--demo` renders the ring on the live Plasma 6 Wayland session (screenshot-verified) + X11 cursor path |
| **Phase 3 — integration + packaging** | **DONE** — daemon→overlay wiring (`ShowMenu(s)->b` + trigger-press path, lazy overlay launch, bounded async name-wait, all off the GLib mainloop); `[overlay] command` + `[radial] default_menu` config keys; `packaging/` (install.sh/uninstall.sh idempotent, `mx4-overlay.service` + `mx4desktop.service` user units, `70-mx-master-4.rules` uaccess udev). Proven live on Plasma 6 Wayland: ShowMenu→lazy-launch→ring appears (screenshot)→hover PlayHaptic buzzes→commit launches plasma-systemmonitor→Hide resident→SIGTERM restores panel divert, no leftover procs. 47 daemon unit tests green |
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
| Daemon | `dev.usidiamond.mx4` | `/dev/usidiamond/mx4` | `dev.usidiamond.mx4.Daemon`: `PlayHaptic(s)->b`, `SetLevel(i)->b`, `ShowMenu(s)->b`; signals `TriggerPressed()`, `TriggerReleased()`, `DeviceLost()` |
| Overlay | `dev.usidiamond.mx4.Overlay` | `/dev/usidiamond/mx4/Overlay` | `dev.usidiamond.mx4.Overlay`: `Show(s menuId)`, `Hide()`; signal `ActionChosen(s)` |

(Distinct bus names so daemon + overlay co-run.) Overlay calls `Daemon.PlayHaptic` on
hover/commit (graceful no-op if daemon absent). In `--demo` the overlay does not register
its service (stays standalone).

## Next steps — Phase 4 (config UI + polish) — RESUME HERE

Phases 1–3 are done and proven on hardware (see table above). What remains:

1. **Config GUI** — a portable Qt6/QML settings window (works on Plasma 6 **and** LXQt)
   editing `~/.config/mx4desktop/config.ini`: ambient sources (enable/waveform/intensity),
   the radial menu segments, trigger, and haptic level. Live-preview a waveform by calling
   `Daemon.PlayHaptic`. Optionally a thin Plasma **KCM** wrapper over the same widget.
2. **Native-Wayland focus** — a small KWin script/effect bridging `activeWindow` changes to
   the daemon (today focus only surfaces via Xwayland `_NET_ACTIVE_WINDOW`).
3. **Physical panel tap** — the one un-automated check: tap the Actions Ring panel and
   confirm `parse_pressed_cids` decodes CID `0x01A0` from a real `divertedButtonsEvent`
   (unit-tested against synthetic reports; divert/restore is hardware-confirmed).
4. **Nice-to-have** — a scriptable `Overlay.Commit(s)` D-Bus method for fully-automated
   Wayland e2e; richer default menu actions; cursor-anchored Wayland overlay via a C++ KWin
   effect plugin (Kando pattern).

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
Commits: `0e2e565` scaffold, `640422d` overlay, `9a72aa1` daemon, `a588e29` docs,
Phase 3 integration + packaging next.
