#!/usr/bin/env python3
"""Minimal, dependency-free proof that the MX Master 4 haptic motor can be
driven directly over HID++ from Linux.

This bypasses Solaar entirely and writes the raw HID++ 2.0 report to the
receiver's hidraw node. It is the exact code path the daemon will use, kept
here as a standalone smoke test / reference implementation.

HID++ 2.0 "play waveform" report (short report, 7 bytes):

    byte0  0x10   report id (0x10 = short HID++; 0x11 = long, 20 bytes)
    byte1  0x02   device index (the MX Master 4 is device 2 on this Bolt rx)
    byte2  0x0B   feature index of HAPTIC (0x19B0) in the device feature table
    byte3  0x4E   (function 0x40 "play" << 4 is already encoded) | sw-id 0xE
    byte4  <wf>   waveform index (see WAVEFORMS below)
    byte5  0x00   padding
    byte6  0x00   padding

IMPORTANT: the feature *index* (byte2) and device *index* (byte1) are not
universal -- they are discovered at runtime via the HID++ root feature on a
real device. The values baked in here match THIS machine's `solaar show`
output and exist only so the smoke test is copy-pasteable. The daemon resolves
them dynamically. See docs/RESEARCH.md.

Usage:
    python3 haptic_test.py                 # play a gentle demo sequence
    python3 haptic_test.py COMPLETED       # play one named waveform
    python3 haptic_test.py 0x07            # play one waveform by index
    sudo python3 haptic_test.py ...        # if your hidraw lacks an ACL
"""
import os
import sys
import time

# /dev/hidraw node of the receiver (or the mouse itself over Bluetooth).
HIDRAW = os.environ.get("MX4_HIDRAW", "/dev/hidraw11")
DEVICE_INDEX = int(os.environ.get("MX4_DEVICE_INDEX", "2"))
HAPTIC_FEATURE_INDEX = int(os.environ.get("MX4_HAPTIC_FINDEX", "0x0B"), 0)

SHORT_REPORT_ID = 0x10
PLAY_FUNCTION_BYTE = 0x4E  # function 0x40 ("play waveform") | software id 0x0E

# Waveform name -> index. Sparse on purpose; the device's capability bitmask
# (HAPTIC function 0x00) says which are actually supported.
WAVEFORMS = {
    "SHARP_STATE_CHANGE": 0x00,
    "DAMP_STATE_CHANGE": 0x01,
    "SHARP_COLLISION": 0x02,
    "DAMP_COLLISION": 0x03,
    "SUBTLE_COLLISION": 0x04,
    "HAPPY_ALERT": 0x05,
    "ANGRY_ALERT": 0x06,
    "COMPLETED": 0x07,
    "SQUARE": 0x08,
    "WAVE": 0x09,
    "FIREWORK": 0x0A,
    "MAD": 0x0B,
    "KNOCK": 0x0C,
    "JINGLE": 0x0D,
    "RINGING": 0x0E,
    "WHISPER_COLLISION": 0x1B,
}


def play(fd: int, waveform_index: int) -> None:
    report = bytes(
        [
            SHORT_REPORT_ID,
            DEVICE_INDEX,
            HAPTIC_FEATURE_INDEX,
            PLAY_FUNCTION_BYTE,
            waveform_index & 0xFF,
            0x00,
            0x00,
        ]
    )
    os.write(fd, report)


def resolve(token: str) -> int:
    token = token.strip().upper().replace(" ", "_")
    if token in WAVEFORMS:
        return WAVEFORMS[token]
    return int(token, 0)  # numeric index, e.g. "0x07" or "7"


def main() -> int:
    if not os.path.exists(HIDRAW):
        print(f"error: {HIDRAW} does not exist; set MX4_HIDRAW", file=sys.stderr)
        return 1
    try:
        fd = os.open(HIDRAW, os.O_RDWR)
    except PermissionError:
        print(f"error: no permission for {HIDRAW}; try sudo or a udev ACL", file=sys.stderr)
        return 1
    try:
        if len(sys.argv) > 1:
            idx = resolve(sys.argv[1])
            print(f"playing waveform 0x{idx:02X}")
            play(fd, idx)
        else:
            demo = ["COMPLETED", "SUBTLE_COLLISION", "WAVE", "JINGLE"]
            for name in demo:
                idx = WAVEFORMS[name]
                print(f"playing {name} (0x{idx:02X})")
                play(fd, idx)
                time.sleep(0.6)
        print("done")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
