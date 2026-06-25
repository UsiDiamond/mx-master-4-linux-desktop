"""Shared pytest fixtures: an in-memory fake HID++ device over a socketpair.

No hardware is required. A background "device" thread reads requests off one end
of a ``socket.socketpair`` and writes plausible HID++ replies/notifications;
:class:`~mx4d.hidpp.HidppTransport` is bound to the other end via its ``fd`` seam.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

import pytest

# Make the package importable when running pytest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mx4d.hidpp import HidppTransport, SOFTWARE_ID  # noqa: E402


class FakeDevice:
    """A scriptable HID++ responder backing a socketpair fd.

    It models a tiny feature table and answers ROOT getFeature / getProtocol,
    DEVICE NAME, HAPTIC capability/level, and REPROG setCidReporting. It can also
    inject unsolicited notifications.
    """

    # feature id -> feature index, matching the real device probed on hardware.
    FEATURE_TABLE = {
        0x0005: 0x03,  # DEVICE NAME
        0x19B0: 0x0B,  # HAPTIC
        0x1B04: 0x0D,  # REPROG CONTROLS V4
    }
    DEVICE_NAME = b"MX Master 4"
    HAPTIC_CAP_MASK = 0x000008FF  # waveforms 0..7 + bit 0x0B as an example
    HAPTIC_LEVEL = 60

    def __init__(self, device_index: int = 2) -> None:
        self.device_index = device_index
        self._dev_sock, self._host_sock = socket.socketpair()
        self.host_fd = os.dup(self._host_sock.fileno())
        self._host_sock.close()
        self._stop = threading.Event()
        self.requests: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # -- injection -------------------------------------------------------
    def send_notification(self, report: bytes) -> None:
        """Push an unsolicited report to the host side."""
        self._dev_sock.sendall(report)

    # -- server ----------------------------------------------------------
    def _serve(self) -> None:
        self._dev_sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data = self._dev_sock.recv(64)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self.requests.append(data)
            reply = self._handle(data)
            if reply is not None:
                try:
                    self._dev_sock.sendall(reply)
                except OSError:
                    break

    def _handle(self, req: bytes) -> bytes | None:
        if len(req) < 4:
            return None
        report_id, dev, findex, fb = req[0], req[1], req[2], req[3]
        fn = fb >> 4
        swid = fb & 0x0F
        length = 20  # reply as a long report

        def pad(payload: bytes) -> bytes:
            return (payload + b"\x00" * length)[:length]

        # ROOT feature (index 0)
        if findex == 0x00:
            if fn == 0x00:  # getFeature
                fid = (req[4] << 8) | req[5]
                idx = self.FEATURE_TABLE.get(fid, 0x00)
                return pad(bytes([0x11, dev, 0x00, fb, idx]))
            if fn == 0x01:  # getProtocolVersion (echo ping marker at byte6)
                return pad(bytes([0x11, dev, 0x00, fb, 0x04, 0x05, req[6] if len(req) > 6 else 0]))

        # DEVICE NAME (index 3)
        if findex == 0x03:
            if fn == 0x00:  # count
                return pad(bytes([0x11, dev, findex, fb, len(self.DEVICE_NAME)]))
            if fn == 0x01:  # get name chunk from offset req[4]
                off = req[4]
                chunk = self.DEVICE_NAME[off : off + 16]
                return pad(bytes([0x11, dev, findex, fb]) + chunk)

        # HAPTIC (index 0x0B)
        if findex == 0x0B:
            if fn == 0x00:  # capabilities
                mask = self.HAPTIC_CAP_MASK.to_bytes(4, "big")
                return pad(bytes([0x11, dev, findex, fb]) + mask)
            if fn == 0x01:  # get level/state: [0]=enabled, [1]=level
                return pad(bytes([0x11, dev, findex, fb, 0x01, self.HAPTIC_LEVEL, 0x00]))
            if fn == 0x02:  # set level (ack echo)
                return pad(bytes([0x11, dev, findex, fb]) + req[4:6])
            if fn == 0x04:  # play (fire and forget; ack anyway)
                return pad(bytes([0x11, dev, findex, fb]) + req[4:5])

        # REPROG CONTROLS V4 (index 0x0D): setCidReporting ack-echoes the params
        if findex == 0x0D and fn == 0x03:
            return pad(bytes([0x11, dev, findex, fb]) + req[4:10])

        # Unknown -> HID++ error: 10 dev ff <feature_index> <func_byte> <err>.
        # Byte 4 echoes the *function byte* (func<<4 | swid) exactly as the real
        # device does, so the transport can match the error to the request.
        return pad(bytes([0x10, dev, 0xFF, findex, fb, 0x01]))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self._dev_sock.close()
        except OSError:
            pass


@pytest.fixture
def fake_device():
    """Yield a started :class:`FakeDevice`."""
    dev = FakeDevice()
    yield dev
    dev.close()


@pytest.fixture
def transport(fake_device):
    """Yield a :class:`HidppTransport` bound to the fake device's host fd."""
    t = HidppTransport(
        "fake", fake_device.device_index, timeout=1.0, fd=fake_device.host_fd
    )
    yield t
    t.close()
