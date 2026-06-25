# mx4d — MX Master 4 Linux daemon (Phase 1)

A standalone, raw-`hidraw` HID++ 2.0 daemon for the Logitech MX Master 4 on
Linux. It drives the mouse's native haptic motor, captures the haptic "Actions
Ring" touch panel as a software trigger, maps ambient desktop events to haptic
waveforms, and exposes a small session D-Bus interface for the (future) C++/Qt6
radial overlay.

It talks to `/dev/hidraw*` directly — it does **not** depend on Solaar /
`logitech_receiver`. No root is required when the receiver's hidraw node carries
a session udev ACL (it does on a normal desktop login). Targets **KDE Plasma 6**
and **LXQt**; the HID/haptics core is desktop-environment agnostic.

## Requirements

- Python 3.11+ (developed/verified on 3.14).
- `python-dbus` + PyGObject (`gi`) for D-Bus + the GLib mainloop.
- `python-Xlib` for the application-focus source (X11 / Xwayland).
- Optional: `pactl` or `pw-mon` for the (opt-in) system-sound source;
  `dbus-monitor` as a fallback for the notifications source.

All optional dependencies degrade gracefully: a missing one disables just that
one source and logs it; the daemon keeps running.

## Device access (no root)

The daemon needs read+write on the receiver's `/dev/hidraw*` node. On a normal
logind desktop session the node is automatically granted a per-session **uaccess
ACL** to the active user, so **no root and no extra setup** are needed — this is
the expected path on KDE Plasma / LXQt.

If your login does *not* grant that ACL (some minimal/headless setups), install a
udev rule and re-plug the receiver (or `udevadm trigger`):

```udev
# /etc/udev/rules.d/70-mx4desktop.rules
# Grant the active session r/w on any Logitech receiver hidraw node.
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", \
  ATTRS{idVendor}=="046d", TAG+="uaccess"
```

Alternatively add yourself to a group that owns the node and grant it r/w. Never
run the daemon as root.

## Run

```bash
cd daemon

# Self-test: find the device, print resolved indices + level + capability mask,
# buzz the mouse (SUBTLE_COLLISION then a COMPLETED-with-fallback), and exit.
python -m mx4d --selftest

# Run the daemon (GLib mainloop).
python -m mx4d

# Run without diverting the Actions Ring panel (leave the mouse fully native).
python -m mx4d --no-trigger

# Debug logging.
python -m mx4d --verbose
```

### Device auto-detection

The daemon scans every Logitech receiver hidraw node (Bolt receivers first) and,
for device indices 1..6, pings the ROOT feature and reads the DEVICE NAME
(`0x0005`) to match "MX Master 4". Node numbering is volatile across reboots, so
nothing is hardcoded.

If auto-detection is slow or flaky on your machine (an idle MX4 can be slow to
wake), set the deterministic override — it targets the exact node and is the
recommended path for the systemd unit:

```bash
MX4_HIDRAW=/dev/hidrawN MX4_DEVICE_INDEX=2 python -m mx4d
```

Find your node with: `for n in /sys/class/hidraw/hidraw*/device/uevent; do
grep -l 'HID_NAME=Logitech USB Receiver' "$n"; done` and pick the one whose
report descriptor advertises report ids `0x10`/`0x11` (the HID++ interface).

### systemd user service

```bash
cp systemd/mx4desktop.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mx4desktop.service
```

The unit is `WantedBy=graphical-session.target` so it starts once the session
bus, display and notification daemon are up. SIGTERM is handled gracefully so
the diverted panel is always restored on stop.

## D-Bus interface

- Bus name: `dev.usidiamond.mx4` (session bus)
- Object path: `/dev/usidiamond/mx4`
- Interface: `dev.usidiamond.mx4.Daemon`

| Member | Type | Signature | Purpose |
|---|---|---|---|
| `PlayHaptic` | method | `s -> b` | Play a waveform by name or index (e.g. overlay tick). The blocking HID++ write is dispatched to the device-I/O worker; returns whether the request was accepted/queued. |
| `SetLevel` | method | `i -> b` | Set the global haptic level (0..100). Dispatched to the device-I/O worker; returns whether the request was accepted/queued. |
| `ShowMenu` | method | `s -> b` | Raise the radial overlay for the given menu id (empty → `[radial] default_menu`). Does exactly what an Actions-Ring press does for the overlay, so it is testable without a physical panel tap. Non-blocking. |
| `TriggerPressed` | signal | — | Emitted when the Actions Ring panel is pressed. |
| `TriggerReleased` | signal | — | Emitted when the Actions Ring panel is released. |
| `DeviceLost` | signal | — | Emitted when the MX Master 4 disappears (unplugged / powered off); the daemon then shuts down cleanly. |

On an Actions-Ring press (or a `ShowMenu` call) the daemon ensures the overlay
is running — **lazily launching** it (config `[overlay] command`) if its bus name
is absent, then waiting briefly and non-blockingly for the name to appear — and
calls `Overlay.Show(menuId)`. The overlay calls back to `PlayHaptic` for segment
ticks. All of this is dispatched off the GLib mainloop, so a slow/idle device or
a slow overlay start never stalls the daemon.

Trigger the overlay without a panel tap:

```bash
dbus-send --session --print-reply --dest=dev.usidiamond.mx4 \
  /dev/usidiamond/mx4 dev.usidiamond.mx4.Daemon.ShowMenu string:default
```

Try it:

```bash
dbus-send --session --print-reply --dest=dev.usidiamond.mx4 \
  /dev/usidiamond/mx4 dev.usidiamond.mx4.Daemon.PlayHaptic string:HAPPY_ALERT
```

## Configuration

INI at `~/.config/mx4desktop/config.ini`, created with defaults on first run.

```ini
[ambient]
enabled = true            ; master enable for all ambient haptics
quiet_hours = false       ; when true, suppress all ambient haptics
debounce_interval = 0.12  ; min seconds between plays (coalesces bursts)

[source:notification]     ; desktop notifications (org.freedesktop.Notifications)
enabled = true
waveform = HAPPY_ALERT    ; critical-urgency notifications upgrade to ANGRY_ALERT
intensity = 70            ; haptic level (0..100) applied for this source

[source:focus]            ; application focus change (X11 _NET_ACTIVE_WINDOW)
enabled = true
waveform = SUBTLE_COLLISION
intensity = 40

[source:sound]            ; system sounds (pactl/pw-mon) — opt-in, coarse
enabled = false
waveform = DAMP_COLLISION
intensity = 50

[trigger]
divert_panel = auto       ; TRI-STATE — how the Actions Ring trigger is captured:
                          ;   auto  = defer to Solaar if a Solaar background
                          ;           process is running (no divert, no
                          ;           contention); otherwise capture the panel
                          ;           ourselves (standalone). This is the default.
                          ;   true  = always capture ourselves (forced standalone).
                          ;   false = never capture; Solaar owns the trigger and
                          ;           its rule fires ShowMenu (daemon does haptics
                          ;           + overlay only). Legacy true/false values in
                          ;           existing configs keep their old meaning.
waveform = HAPPY_ALERT    ; played on a trigger press (placeholder)

[radial]
center/command = ...      ; auto-detected task manager (see below)
center/label   = Task Manager
center/icon    = utilities-system-monitor
default_menu   = default  ; menu id passed to Overlay.Show() on a trigger press

[overlay]
command = mx4-radial      ; how the daemon lazily launches the overlay process;
                          ; a bare name is resolved on PATH, an absolute path is
                          ; accepted (for dev/testing against a build directory)
```

The `[radial] center/command` defaults to the auto-detected system monitor:
`plasma-systemmonitor` (KDE) → `qps` / `lxtask` (LXQt) →
`gnome-system-monitor` → `ksysguard` (deprecated, last), falling back to
`xterm -e htop`. This is the **same key** the C++/Qt6 overlay's `MenuConfig`
reads, so editing it affects both the daemon and the future overlay. (The legacy
`center_action` key is still read for backward compatibility.)

## Known limitations / honest notes

- **Waveform support is firmware-gated.** The MX4 we tested exposes only a
  subset (capability mask `0x0001003C`: SHARP/DAMP/SUBTLE_COLLISION, HAPPY_ALERT,
  and an undocumented `0x10`). `COMPLETED` and several others are **not**
  supported by that firmware. The engine checks the device's capability bitmask
  and, for ambient events, falls back to the closest supported waveform rather
  than going silent. The defaults ship as supported waveforms.
- **Wayland focus changes:** the focus source watches X11 `_NET_ACTIVE_WINDOW`
  (native on LXQt/X11; covers Xwayland on Plasma). Native-Wayland-only clients
  may not surface there — a KWin-script bridge is the planned complement.
- **System sounds** are best-effort and off by default (coarse: any new playback
  stream triggers it, and notification sounds are already covered by the
  notifications source).
- **Idle-device wake:** an idle MX4 can be slow to answer the first request;
  auto-detection retries across a few passes. The `MX4_HIDRAW`/`MX4_DEVICE_INDEX`
  override is the fast, deterministic path.
- The **radial overlay** itself is a later phase (C++/Qt6 + QML). This daemon
  only logs "menu requested", buzzes, and emits the D-Bus trigger signal.

## Tests

Unit tests run against an in-memory fake hidraw (no hardware needed):

```bash
cd daemon
pytest -q        # 63 tests
```

They cover request framing / func_byte math, response demux, getFeature parsing,
the waveform table + capability gating + fallback, the play-packet byte
contract, setCidReporting param construction, press/release detection, config
defaults + persistence (incl. the `divert_panel` tri-state + bool back-compat),
Solaar background-process detection, the auto defer decision, and task-manager
detection.

### Solaar-first: automatic trigger deferral

With `divert_panel = auto` (the default) the daemon cheaply scans `/proc` for a
running Solaar background process. If Solaar is present it **does not** divert the
Actions Ring panel — Solaar owns it and its rule fires `ShowMenu` — so there is
no device contention; the daemon still provides haptics, ambient mapping and the
overlay. If Solaar is absent the daemon captures the panel itself (standalone).
The detector never imports `logitech_receiver` and returns `False` (never raises)
when Solaar is not installed, so the standalone path never depends on Solaar. To
also install the Solaar rule, run `packaging/solaar/setup-solaar.sh`. Force either
behaviour explicitly with `divert_panel = true` (always capture) or `false`
(never capture).
