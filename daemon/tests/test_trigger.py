"""Unit tests for the trigger: setCidReporting params, press/release detection."""

from __future__ import annotations

import time

from mx4d.trigger import (
    ACTIONS_RING_CID,
    TriggerWatcher,
    build_set_cid_reporting_params,
    parse_pressed_cids,
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
    last_set = [
        r for r in fake_device.requests if r[2] == 0x0D and (r[3] >> 4) == 0x3
    ][-1]
    assert not (last_set[6] & (1 << 1))  # divert bit cleared on restore


def test_divert_disabled_does_nothing(transport, fake_device):
    watcher = TriggerWatcher(transport, 0x0D, divert=False)
    assert watcher.start() is False
    watcher.stop()  # must not raise
