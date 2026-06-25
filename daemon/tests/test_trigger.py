"""Unit tests for the trigger: setCidReporting params, press/release detection."""

from __future__ import annotations

import time

from mx4d.trigger import (
    ACTIONS_RING_CID,
    TriggerWatcher,
    build_set_cid_reporting_params,
    parse_pressed_cids,
    parse_raw_xy,
)


def test_set_cid_reporting_params_divert_on():
    params = build_set_cid_reporting_params(ACTIONS_RING_CID, divert=True)
    assert params[0] == 0x01 and params[1] == 0xA0  # CID big-endian
    flags = params[2]
    assert flags & (1 << 1)  # divert bit set
    assert flags & (1 << 5)  # divert-valid (update) bit set
    assert params[3] == 0x00 and params[4] == 0x00  # no remap


def test_set_cid_reporting_params_divert_off():
    params = build_set_cid_reporting_params(ACTIONS_RING_CID, divert=False)
    flags = params[2]
    assert not (flags & (1 << 1))  # divert bit clear
    assert flags & (1 << 5)  # but the valid bit is still set so it applies


def test_parse_pressed_cids():
    # payload starts at offset 4; big-endian 16-bit CIDs, 0 terminates.
    report = bytes([0x11, 2, 0x0D, 0x00, 0x01, 0xA0, 0x00, 0x00] + [0] * 12)
    assert parse_pressed_cids(report) == [0x01A0]
    report2 = bytes([0x11, 2, 0x0D, 0x00, 0x00, 0x00] + [0] * 14)
    assert parse_pressed_cids(report2) == []


def test_press_release_cycle(transport, fake_device):
    presses: list[int] = []
    releases: list[int] = []
    watcher = TriggerWatcher(
        transport,
        0x0D,
        on_press=presses.append,
        on_release=releases.append,
    )
    assert watcher.start() is True  # diverts via fake (which acks)

    # Press: notification listing CID 0x01A0.
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x00, 0x01, 0xA0] + [0] * 14)
    )
    time.sleep(0.1)
    # Release: notification with no CIDs.
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x00, 0x00, 0x00] + [0] * 14)
    )
    time.sleep(0.1)

    assert presses == [ACTIONS_RING_CID]
    assert releases == [ACTIONS_RING_CID]

    watcher.stop()
    # stop() must have sent a non-diverted setCidReporting (flags w/o divert bit).
    last_set = [r for r in fake_device.requests if r[2] == 0x0D and (r[3] >> 4) == 0x3][
        -1
    ]
    assert not (last_set[6] & (1 << 1))  # divert bit cleared on restore


def test_divert_disabled_does_nothing(transport, fake_device):
    # Neither diverting nor listening -> the watcher has nothing to do.
    watcher = TriggerWatcher(transport, 0x0D, divert=False)
    assert watcher.start() is False
    watcher.stop()  # must not raise


def _press(fake_device):
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x00, 0x01, 0xA0] + [0] * 14)
    )


def _release(fake_device):
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x00, 0x00, 0x00] + [0] * 14)
    )


def test_tap_fires_on_short_release(transport, fake_device):
    taps: list[int] = []
    holds: list[int] = []
    watcher = TriggerWatcher(
        transport, 0x0D, hold_threshold=0.3, on_tap=taps.append, on_hold=holds.append
    )
    assert watcher.start() is True
    # Press then release well within the threshold -> a tap, not a hold.
    _press(fake_device)
    time.sleep(0.05)
    _release(fake_device)
    time.sleep(0.05)
    assert taps == [ACTIONS_RING_CID]
    assert holds == []
    watcher.stop()


def test_hold_fires_after_threshold(transport, fake_device):
    taps: list[int] = []
    holds: list[int] = []
    watcher = TriggerWatcher(
        transport, 0x0D, hold_threshold=0.05, on_tap=taps.append, on_hold=holds.append
    )
    assert watcher.start() is True
    # Press and keep it down past the threshold -> a hold fires before release.
    _press(fake_device)
    time.sleep(0.2)
    assert holds == [ACTIONS_RING_CID]
    # Releasing after a hold must NOT also fire a tap.
    _release(fake_device)
    time.sleep(0.05)
    assert taps == []
    watcher.stop()


def test_coexist_divert_is_fire_and_forget(transport, fake_device):
    # confirm=False: start() sends the divert as a raw write (no reply awaited)
    # and still reports success, so capture works under a running Solaar.
    watcher = TriggerWatcher(transport, 0x0D, confirm=False)
    assert watcher.start() is True
    # Fire-and-forget: the write returns before the fake thread records it.
    time.sleep(0.05)
    sets = [r for r in fake_device.requests if r[2] == 0x0D and (r[3] >> 4) == 0x3]
    assert sets, "expected a setCidReporting write"
    assert sets[-1][6] & (1 << 1)  # divert bit set
    watcher.stop()


def test_listen_only_subscribes_without_diverting(transport, fake_device):
    # divert=False, listen=True: send NO setCidReporting, but a press still
    # reaches on_tap (something else, e.g. Solaar, owns the divert).
    taps: list[int] = []
    watcher = TriggerWatcher(
        transport,
        0x0D,
        divert=False,
        listen=True,
        hold_threshold=0.3,
        on_tap=taps.append,
    )
    assert watcher.start() is True
    assert not [r for r in fake_device.requests if r[2] == 0x0D and (r[3] >> 4) == 0x3]
    _press(fake_device)
    time.sleep(0.05)
    _release(fake_device)
    time.sleep(0.05)
    assert taps == [ACTIONS_RING_CID]
    watcher.stop()


def _raw_xy(fake_device, dx: int, dy: int):
    """Inject a divertedRawXYEvent (function 0x01) carrying signed dx/dy."""
    payload = dx.to_bytes(2, "big", signed=True) + dy.to_bytes(2, "big", signed=True)
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x10]) + payload + b"\x00" * 12
    )


def test_parse_raw_xy_signed_and_short():
    # function byte 0x10 -> rawXY; payload is signed big-endian dx, dy.
    report = bytes([0x11, 2, 0x0D, 0x10, 0x01, 0x2C, 0xFF, 0xCE] + [0] * 12)
    assert parse_raw_xy(report) == (300, -50)
    # A truncated report yields (0, 0) instead of raising.
    assert parse_raw_xy(bytes([0x11, 2, 0x0D, 0x10, 0x01])) == (0, 0)


def test_raw_xy_forwarded_only_while_pressed(transport, fake_device):
    moves: list[tuple[int, int]] = []
    watcher = TriggerWatcher(
        transport, 0x0D, on_raw_xy=lambda dx, dy: moves.append((dx, dy))
    )
    assert watcher.start() is True

    # A rawXY event BEFORE any press is ignored (we are not pressed).
    _raw_xy(fake_device, 10, 20)
    time.sleep(0.05)
    assert moves == []

    # Press, then two slides, then a zero sample (dropped), then release. The
    # short gaps keep each report in its own read() — a real hidraw delivers one
    # report per read; the socketpair fake would otherwise coalesce them.
    _press(fake_device)
    time.sleep(0.05)
    _raw_xy(fake_device, 300, -50)
    time.sleep(0.02)
    _raw_xy(fake_device, -5, 7)
    time.sleep(0.02)
    _raw_xy(fake_device, 0, 0)  # no direction -> dropped
    time.sleep(0.05)
    _release(fake_device)
    time.sleep(0.05)
    assert moves == [(300, -50), (-5, 7)]

    # After release we are no longer pressed -> further rawXY is ignored.
    _raw_xy(fake_device, 99, 99)
    time.sleep(0.05)
    assert moves == [(300, -50), (-5, 7)]
    watcher.stop()


def test_raw_xy_does_not_disturb_button_routing(transport, fake_device):
    # With an on_raw_xy handler wired, a normal press/release (function 0x00)
    # must still produce a tap exactly as before — the function-nibble routing
    # keeps the two event kinds separate.
    taps: list[int] = []
    moves: list[tuple[int, int]] = []
    watcher = TriggerWatcher(
        transport,
        0x0D,
        hold_threshold=0.3,
        on_tap=taps.append,
        on_raw_xy=lambda dx, dy: moves.append((dx, dy)),
    )
    assert watcher.start() is True
    _press(fake_device)
    time.sleep(0.05)
    _release(fake_device)
    time.sleep(0.05)
    assert taps == [ACTIONS_RING_CID]
    assert moves == []  # no rawXY events were sent
    watcher.stop()
