"""Unit tests for device-name reading and feature resolution against the fake."""

from __future__ import annotations

from mx4d.device import read_device_name


def test_read_device_name(transport):
    # The fake DEVICE NAME feature is at index 3 and returns "MX Master 4".
    name = read_device_name(transport, 0x03)
    assert name == "MX Master 4"
