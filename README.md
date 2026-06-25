# mx-master-4-desktop

Bring the Logitech **MX Master 4**'s Windows-only features — the **Actions Ring**
radial menu and **native haptics** — to the Linux desktop, on **KDE Plasma 6** and
**LXQt**.

Logitech ships these features only through Logi Options+ on Windows 11 and macOS
([haptics announcement](https://support.logi.com/hc/en-us/articles/40581588219671-MX-Master-4-Native-Haptics-with-Windows-11)).
This project reimplements them natively on Linux.

> Status: **early scaffolding.** The core technical risk is already retired — see
> "Proven" below. Architecture and protocol are documented; the daemon and overlay
> are next. Read [docs/STATUS.md](docs/STATUS.md) first when resuming.

## What it does (target)

- **Radial menu ("Actions Ring")** — a circular pop-up menu summoned by the mouse's
  haptic touch panel (or a hotkey), with the **Task Manager / system monitor as the
  default action**. Segments are user-configurable (launch app, switch desktop, media
  control, custom command). Selection ticks the haptic motor as you move between
  segments.
- **Ambient haptics** — the mouse buzzes in response to **desktop notifications,
  system sounds, and application-focus changes**, with a configurable waveform per
  event type and a global intensity level.
- **Desktops** — KDE Plasma 6 (Wayland + X11) and LXQt (X11). DE-agnostic core; thin
  per-DE shims for the overlay and focus events.

## Proven (on real hardware, 2026-06-24)

The MX Master 4 haptic motor is driven **directly over HID++** from Linux — no Solaar
dependency, no root (a udev ACL on the active session is enough):

```bash
python3 tools/haptic_test.py            # plays a gentle waveform demo
python3 tools/haptic_test.py COMPLETED  # play one named waveform
```

This writes a raw HID++ 2.0 report to the receiver's `hidraw` node. The same code
path is what the daemon uses. See [tools/haptic_test.py](tools/haptic_test.py) and
[docs/RESEARCH.md](docs/RESEARCH.md).

Device facts (this machine): MX Master 4, WPID `B042`, HID++ 4.5, on a Logi Bolt
receiver (`046d:C548`) as device index `2`. Haptics are HID++ feature `HAPTIC`
(`0x19B0`), feature index `0x0B` on this device.

## Repository layout

```
tools/haptic_test.py   standalone raw-HID++ haptic smoke test (works today)
docs/RESEARCH.md       protocol + KDE/Wayland overlay research, with sources
docs/ARCHITECTURE.md   planned components, tech stack, event model
docs/STATUS.md         progress log + resume anchor (READ FIRST when resuming)
```

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Builds on reverse-engineering by the [Solaar](https://github.com/pwr-Solaar/Solaar)
project (haptic feature `0x19B0`), and takes architectural cues from
[Kando](https://github.com/kando-menu/kando) (pie menu on KDE Wayland),
[koverlay](https://github.com/erik96/koverlay) (LayerShellQt overlay), and
[mx4notifications](https://github.com/lukasfri/mx4notifications) (notification-driven
haptics). Not affiliated with or endorsed by Logitech.
