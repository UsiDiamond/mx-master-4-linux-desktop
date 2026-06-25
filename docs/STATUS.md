# STATUS — read first when resuming

Project: bring the MX Master 4 **Actions Ring** + **native haptics** to Linux on
**KDE Plasma 6** and **LXQt**. Private repo under the UsiDiamond GitHub account.

Last updated: **2026-06-24** (Phases 1–4 complete, committed + pushed. REBOOT
CHECKPOINT — working tree clean, `HEAD=a3b8154` in sync with origin, daemon stopped
and Actions Ring panel restored). Proven on real hw / round-tripped against both parsers.

## Where things stand

| Area | State |
|---|---|
| Repo + license + docs | **Done** |
| Device identified (real hw) | **Done** — MX Master 4, `046d:B042`, HID++ 4.5, Bolt rx, device index 2. NOTE: hidraw node number is volatile across reboots/reconnects (seen as `hidraw11` then `hidraw7`); the daemon auto-detects, so don't rely on a fixed node |
| **Phase 1 — daemon** (`daemon/`, Python) | **DONE + committed** (`9a72aa1`). Standalone raw-HID++, no Solaar dep. Verified on hardware: selftest buzzes; `notify-send`→haptic; D-Bus `PlayHaptic`/`SetLevel`; trigger divert+restore clean; 36 unit tests pass |
| **Phase 2 — overlay** (`overlay/`, C++/Qt6) | **DONE + committed** (`640422d`). Builds clean vs Qt6 6.11 + LayerShellQt; `--demo` renders the ring on the live Plasma 6 Wayland session (screenshot-verified) + X11 cursor path |
| **Phase 3 — integration + packaging** | **DONE** — daemon→overlay wiring (`ShowMenu(s)->b` + trigger-press path, lazy overlay launch, bounded async name-wait, all off the GLib mainloop); `[overlay] command` + `[radial] default_menu` config keys; `packaging/` (install.sh/uninstall.sh idempotent, `mx4-overlay.service` + `mx4desktop.service` user units, `70-mx-master-4.rules` uaccess udev). Proven live on Plasma 6 Wayland: ShowMenu→lazy-launch→ring appears (screenshot)→hover PlayHaptic buzzes→commit launches plasma-systemmonitor→Hide resident→SIGTERM restores panel divert, no leftover procs. 47 daemon unit tests green |
| **Phase 4 — config GUI + polish** | **DONE** — portable Qt6/QML settings window (`config-ui/`, `mx4-config`, no KF6; Plasma 6 + LXQt) editing the shared INI (configparser-compatible writer, preserves unknown keys, round-trip proven against BOTH daemon `config.py` and overlay `MenuConfig`); live waveform preview + firmware capability-mask marking via `Daemon.GetCapabilities()->u`. Polish: `Overlay.Commit(s)->b` / `Activate(i)->b` (scriptable Wayland e2e), daemon `FocusChanged(s)->b` + `mx4-focus-bridge` KWin script (installed NOT enabled) for native-Wayland focus. `install.sh`/`uninstall.sh` updated |

## Solaar-first integration (chosen direction, 2026-06-24)

User decision: **make it primarily work with Solaar, with a self-sufficient fallback.**
Principle (user): *keep each path working on its own — the standalone build must never hard-
depend on Solaar or anything else; Solaar-first is purely additive/opt-in.*

- **Solaar-first** (when Solaar runs): Solaar owns the device + diverts the Actions Ring
  panel; a Solaar **rule** (Key `Haptic` pressed → `Execute` `dbus-send … Daemon.ShowMenu`)
  pops the overlay. The daemon runs with `[trigger] divert_panel = false` so it does NOT
  fight Solaar — it still provides the overlay, haptics, and ambient→haptic mapping.
- **Fallback / default**: with no Solaar, the daemon diverts + captures the panel itself
  (unchanged). Default config keeps `divert_panel = true` so standalone works out of the box.
- **Shipped now** (no code change — uses the existing `divert_panel` flag): `packaging/solaar/`
  = `setup-solaar.sh` (idempotent; `--install-rule`, `--revert`), `mx4-rules.yaml`, `README.md`.
- **Next (workflow):** make the daemon **auto-detect** a running Solaar and flip
  `divert_panel` itself (no manual setup), and optionally route haptics through Solaar's
  `feature_request` when Solaar holds the device. Standalone stays the zero-dependency default.

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
| Daemon | `dev.usidiamond.mx4` | `/dev/usidiamond/mx4` | `dev.usidiamond.mx4.Daemon`: `PlayHaptic(s)->b`, `SetLevel(i)->b`, `ShowMenu(s)->b`, `GetCapabilities()->u`, `FocusChanged(s)->b`; signals `TriggerPressed()`, `TriggerReleased()`, `DeviceLost()` |
| Overlay | `dev.usidiamond.mx4.Overlay` | `/dev/usidiamond/mx4/Overlay` | `dev.usidiamond.mx4.Overlay`: `Show(s menuId)`, `Hide()`, `Commit(s)->b`, `Activate(i)->b`; signal `ActionChosen(s)` |

(Distinct bus names so daemon + overlay co-run.) Overlay calls `Daemon.PlayHaptic` on
hover/commit (graceful no-op if daemon absent). In `--demo` the overlay does not register
its service (stays standalone).

## Next steps — RESUME HERE (post-reboot)

Phases 1–4 are DONE + committed + pushed. The radial menu, ambient haptics, config GUI,
and packaging all work: `ShowMenu`→ring was confirmed live (user saw it on Plasma Wayland),
haptics are felt on real hardware, mx4-config round-trips both parsers. Open items:

1. **Confirm the physical panel-tap trigger** — the one un-automated check (the log monitor
   timed out before a tap happened). Start the daemon, tap the haptic panel; the ring should
   open. We can't press the panel from software; `parse_pressed_cids` decodes CID `0x01A0`
   and is unit-tested against synthetic `divertedButtonsEvent` reports; divert+restore is
   hardware-confirmed. If a tap does nothing, capture the raw diverted notification to see
   which CID the panel actually emits and fix the decode.
2. **OpenRC + systemd dual-init install** — THIS box is Gentoo/OpenRC (no `systemctl --user`!).
   Rework `install.sh`/`uninstall.sh` to detect the init and default to **XDG autostart**
   (`~/.config/autostart/mx4desktop.desktop` running `mx4d`, which lazy-spawns the overlay);
   keep systemd user units optional. Saved as a requirement in agent memory.
3. **Distro packages** (workflow queued, NOT started) — Gentoo ebuild (OpenRC-default +
   `systemd` USE flag), Arch PKGBUILD, Debian/Ubuntu, Fedora `.spec`; build-test Gentoo
   locally via `ebuild`, the others in Docker (available). Add `docs/INSTALL.md` with Gentoo
   instructions. NOTE: this packaging must include `mx4-config` + the KWin script.

### Run it on OpenRC right now (this box)

    mx4d --verbose      # daemon; lazy-launches the overlay; Ctrl-C restores the panel
    dbus-send --session --dest=dev.usidiamond.mx4 /dev/usidiamond/mx4 \
      dev.usidiamond.mx4.Daemon.ShowMenu string:default      # or tap the panel
    mx4-config          # settings GUI
    # autostart without systemd: ~/.config/autostart/mx4desktop.desktop with Exec=mx4d

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
- THIS dev box is **OpenRC** — no `systemctl --user`; use XDG autostart. install.sh/packages
  must be init-agnostic (XDG autostart primary, systemd units optional).
- KWin focus-bridge is **Plasma-Wayland-only**; on X11/LXQt the `_NET_ACTIVE_WINDOW` focus
  source is native and complete (no KWin script needed).
- Trigger-divert restore on shutdown may need a retry (attempt 1 can time out with "no reply
  for feature_index=0x0D"; attempt 2 succeeds) — by design; panel ends up non-diverted.

## Local checkout

`/home/magus/GitHub/mx-master-4-desktop`. Remote `UsiDiamond/mx-master-4-desktop` (private).
Commits: `0e2e565` scaffold, `640422d` overlay, `9a72aa1` daemon, `a588e29` docs,
`6cd6e07` integration+packaging, `a3b8154` config GUI + polish. All pushed (HEAD=a3b8154).
