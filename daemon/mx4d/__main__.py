"""Command-line entry point for the mx4 daemon.

Usage::

    python -m mx4d                 # run the daemon under a GLib mainloop
    python -m mx4d --no-trigger    # run without diverting the Actions Ring panel
    python -m mx4d --selftest      # open device, print resolved indices + level
                                   # + capability mask, buzz, and exit
    python -m mx4d --verbose       # debug logging
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .daemon import Mx4Daemon
from .device import find_mx_master_4
from .haptics import WAVEFORM_NAMES, HapticEngine


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def run_selftest() -> int:
    """Open the device, print its state, play two waveforms, then exit.

    Plays SUBTLE_COLLISION then COMPLETED (both gated by the capability mask).
    This buzzes the physical mouse.
    """
    device = find_mx_master_4()
    try:
        print(f"device:        {device.name}")
        print(f"hidraw node:   {device.path}")
        print(f"device index:  {device.device_index}")
        print(f"haptic index:  0x{device.haptic_index:02X}")
        print(f"reprog index:  0x{device.reprog_index:02X}")

        engine = HapticEngine(device.transport, device.haptic_index)
        mask = engine.read_capabilities()
        print(f"capability mask: 0x{mask:08X}")
        supported = [
            WAVEFORM_NAMES.get(i, f"0x{i:02X}") for i in range(32) if (1 << i) & mask
        ]
        print(f"supported waveforms: {', '.join(supported)}")
        print(f"haptic enabled: {engine.is_enabled()}")
        print(f"haptic level:   {engine.get_level()}")

        import time

        for name in ("SUBTLE_COLLISION", "COMPLETED"):
            # Strict (no fallback) so the selftest truthfully reports gating.
            played = engine.play(name, force=True, fallback=False)
            status = "ok" if played else "gated (unsupported by firmware)"
            print(f"play {name}: {status}")
            time.sleep(0.6)
        # Also demonstrate the runtime fallback the daemon uses for events.
        played = engine.play("COMPLETED", force=True, fallback=True)
        print(f"play COMPLETED (with fallback): {'ok' if played else 'failed'}")
        print("selftest done")
        return 0
    finally:
        device.close()


def main(argv: list[str] | None = None) -> int:
    """Parse args and dispatch to selftest or the daemon run loop."""
    parser = argparse.ArgumentParser(
        prog="mx4d", description="MX Master 4 Linux daemon"
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="open the device, print resolved indices + level + capability mask, "
        "play SUBTLE_COLLISION then COMPLETED, and exit",
    )
    parser.add_argument(
        "--no-trigger",
        action="store_true",
        help="do not divert the Actions Ring panel (leave the mouse fully native)",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    try:
        if args.selftest:
            return run_selftest()
        config = load_config()
        daemon = Mx4Daemon(config=config, enable_trigger=not args.no_trigger)
        return daemon.run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
