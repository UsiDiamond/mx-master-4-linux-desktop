"""Unit tests for the HID++ transport: framing, demux, getFeature, errors."""

from __future__ import annotations

import threading
import time

from mx4d.hidpp import (
    SHORT_REPORT_ID,
    LONG_REPORT_ID,
    SOFTWARE_ID,
    HidppError,
    HidppTimeout,
    func_byte,
)


def test_func_byte_math():
    # (function_id << 4) | software_id, software id pinned to 0x0E.
    assert func_byte(0x4) == 0x4E  # haptic "play"
    assert func_byte(0x0) == 0x0E  # getFeature/getCapabilities
    assert func_byte(0x3) == 0x3E  # setCidReporting
    assert func_byte(0xF, 0x0E) == 0xFE
    assert func_byte(0x4, 0x00) == 0x40


def test_request_framing(transport, fake_device):
    # A short getFeature request must be framed exactly.
    transport.get_feature(0x19B0)
    req = fake_device.requests[-1]
    assert req[0] == SHORT_REPORT_ID
    assert req[1] == fake_device.device_index
    assert req[2] == 0x00  # ROOT feature index
    assert req[3] == func_byte(0x00)  # 0x0E
    assert req[4] == 0x19 and req[5] == 0xB0  # feature id hi/lo


def test_getfeature_parsing(transport):
    # Indices come back per the fake feature table (matches real hardware).
    assert transport.get_feature(0x0005) == 0x03
    assert transport.get_feature(0x19B0) == 0x0B
    assert transport.get_feature(0x1B04) == 0x0D
    # Absent feature resolves to 0.
    assert transport.get_feature(0xDEAD) == 0x00


def test_get_protocol_version(transport):
    major, minor = transport.get_protocol_version()
    assert (major, minor) == (4, 5)


def test_response_demux_only_matches_our_swid(transport, fake_device):
    # A reply with the wrong software id must NOT satisfy a call (it would be a
    # notification). Inject a bogus report on the haptic feature, then a real
    # getFeature must still get its own reply.
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0B, 0x00] + [0] * 16)
    )
    time.sleep(0.05)
    assert transport.get_feature(0x19B0) == 0x0B


def test_long_request_framing(transport, fake_device):
    transport.call(0x0D, 0x3, 0x01, 0xA0, 0x20, long=True)
    req = fake_device.requests[-1]
    assert req[0] == LONG_REPORT_ID
    assert len(req) == 20
    assert req[3] == func_byte(0x3)


def test_error_reply_raises(transport):
    # Calling an unmapped feature/function makes the fake emit a HID++ error.
    try:
        transport.call(0x7F, 0x9)
    except HidppError as exc:
        assert exc.error_code == 0x01
    else:
        raise AssertionError("expected HidppError")


def test_stale_error_does_not_misroute(transport, fake_device):
    # A late HID++ error whose embedded feature/function do NOT match the
    # in-flight request must be discarded, not raised on the next call. Inject an
    # error report for feature 0x7F/function 0x9 while a getFeature (ROOT 0x00,
    # function 0x00) is the one we actually issue: it must succeed normally.
    fake_device.send_notification(
        bytes([0x10, fake_device.device_index, 0xFF, 0x7F, func_byte(0x9), 0x01]
              + [0] * 14)
    )
    time.sleep(0.05)
    # ROOT getFeature must still resolve correctly (no spurious HidppError).
    assert transport.get_feature(0x19B0) == 0x0B


def test_notification_dispatch(transport, fake_device):
    seen: list[bytes] = []
    event = threading.Event()

    def cb(report: bytes) -> None:
        seen.append(report)
        event.set()

    transport.add_notification_callback(cb, feature_index=0x0D)
    # software id 0 => notification, on feature index 0x0D.
    fake_device.send_notification(
        bytes([0x11, fake_device.device_index, 0x0D, 0x00, 0x01, 0xA0] + [0] * 14)
    )
    assert event.wait(1.0)
    assert seen and seen[0][2] == 0x0D


def test_timeout(fake_device):
    from mx4d.hidpp import HidppTransport

    # Bind a transport but ask for a feature the fake answers, then a function
    # that yields no reply path is hard to force; instead test the timeout via a
    # very short timeout against a closed device.
    t = HidppTransport("fake", 2, timeout=0.2, fd=fake_device.host_fd)
    try:
        fake_device.close()  # device stops answering
        time.sleep(0.05)
        raised = False
        try:
            t.get_feature(0x0005)
        except (HidppTimeout, OSError):
            raised = True
        assert raised
    finally:
        t.close()
