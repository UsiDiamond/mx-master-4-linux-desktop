"""Locate the MX Master 4 and bind a HID++ transport to it.

Node numbering is volatile (it changes across reboots / re-pairing), so we do
**not** hardcode a hidraw path or device index. We scan every Logitech receiver
hidraw node and, for each plausible device index, ping the ROOT feature and read
the device's name via the DEVICE NAME feature (``0x0005``) to match
``MX Master 4``. The verified-on-hardware values are only used as a fallback
via the ``MX4_HIDRAW`` / ``MX4_DEVICE_INDEX`` environment variables.
"""

from __future__ import annotations

import glob
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from .hidpp import HidppTransport, HidppError, HidppTimeout

logger = logging.getLogger(__name__)

# HID++ 2.0 feature ids we resolve at runtime.
FEATURE_DEVICE_NAME = 0x0005
FEATURE_HAPTIC = 0x19B0
FEATURE_REPROG_CONTROLS_V4 = 0x1B04

# DEVICE NAME (0x0005) function ids.
DEVICE_NAME_FN_GET_COUNT = 0x00
DEVICE_NAME_FN_GET_NAME = 0x01

# Substring that identifies a Logitech receiver in the HID uevent HID_NAME.
RECEIVER_HID_NAME = "Logitech USB Receiver"

# The model name we are hunting for (case-insensitive substring match).
TARGET_NAME = "MX Master 4"

# Plausible device indices to probe on a receiver (1..6 per HID++).
PROBE_DEVICE_INDICES = range(1, 7)

# Number of ping attempts per index during a scan. A few consecutive nudges
# wake a lightly-idle MX4; broken-pipe (wrong-interface) writes fail fast and
# never consume the full budget. NOTE: a *deeply* asleep MX4 (no physical
# interaction for a while) may not wake from pings at all — that is a hardware
# behaviour, not a bug. The MX4_HIDRAW / MX4_DEVICE_INDEX env override targets
# the exact node and is the recommended deterministic path (it concentrates the
# wake retries on the right index). The shipped systemd unit can set them.
SCAN_ATTEMPTS = 4

# How many full scan passes to make before giving up. Earlier passes wake an
# idle device; later passes then match it. Broken-pipe (non-HID++) nodes fail
# fast, so extra passes stay cheap.
SCAN_PASSES = 3

# More attempts when an explicit node is given (override path): all retries land
# on the right index, so a generous budget is cheap and maximises wake success.
OVERRIDE_ATTEMPTS = 8

# Short pause between wake attempts so the device has time to come back.
WAKE_RETRY_DELAY = 0.15


@dataclass
class MX4Device:
    """A resolved MX Master 4: its transport plus key feature indices.

    The caller owns :attr:`transport` and must call ``transport.close()`` (or
    :meth:`close`) when done.
    """

    transport: HidppTransport
    path: str
    device_index: int
    name: str
    haptic_index: int
    reprog_index: int

    def close(self) -> None:
        """Close the underlying transport."""
        self.transport.close()


def _sysfs_hid_name(hidraw_node: str) -> str:
    """Return the ``HID_NAME`` uevent value for a ``/dev/hidrawN`` node.

    Returns an empty string if it cannot be read.
    """
    name = os.path.basename(hidraw_node)
    uevent = f"/sys/class/hidraw/{name}/device/uevent"
    try:
        with open(uevent, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("HID_NAME="):
                    return line[len("HID_NAME=") :].strip()
    except OSError:
        return ""
    return ""


# Logi Bolt receiver product id (the MX Master 4 pairs to a Bolt dongle). Nodes
# behind a Bolt receiver are probed first so wake retries land on the most
# likely node early.
BOLT_RECEIVER_PID = "C548"


def _sysfs_hid_id(hidraw_node: str) -> str:
    """Return the ``HID_ID`` uevent value (e.g. ``0003:0000046D:0000C548``)."""
    name = os.path.basename(hidraw_node)
    uevent = f"/sys/class/hidraw/{name}/device/uevent"
    try:
        with open(uevent, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("HID_ID="):
                    return line[len("HID_ID=") :].strip()
    except OSError:
        return ""
    return ""


def list_receiver_nodes() -> list[str]:
    """Return ``/dev/hidraw*`` nodes whose HID_NAME is a Logitech receiver.

    Bolt-receiver nodes (where an MX Master 4 pairs) are listed first, then the
    rest; within each group the order is deterministic.
    """
    bolt: list[str] = []
    other: list[str] = []
    for node in sorted(glob.glob("/dev/hidraw*")):
        if RECEIVER_HID_NAME not in _sysfs_hid_name(node):
            continue
        if BOLT_RECEIVER_PID in _sysfs_hid_id(node).upper():
            bolt.append(node)
        else:
            other.append(node)
    return bolt + other


def read_device_name(transport: HidppTransport, name_index: int) -> str:
    """Read a device's marketing name via the DEVICE NAME feature (0x0005).

    Reads the length (function ``0x00``) then pulls the name in chunks
    (function ``0x01``, 16 bytes per call from a starting offset).
    """
    count_reply = transport.call(name_index, DEVICE_NAME_FN_GET_COUNT)
    length = count_reply[4]
    chunks = bytearray()
    offset = 0
    while offset < length:
        reply = transport.call(name_index, DEVICE_NAME_FN_GET_NAME, offset)
        # The name bytes start at offset 4 of the reply (max 16 per chunk).
        chunk = reply[4 : 4 + min(16, length - offset)]
        if not chunk:
            break
        chunks += chunk
        offset += len(chunk)
    return chunks.decode("utf-8", errors="replace").rstrip("\x00").strip()


def _ping_with_retries(transport: HidppTransport, attempts: int) -> bool:
    """Ping ROOT getProtocolVersion, retrying to wake an idle device.

    Returns ``True`` on the first successful reply. A :class:`HidppError`
    counts as alive (the index exists). A broken-pipe ``OSError`` is a *write*
    rejection (wrong interface or unpaired index) — deterministic, so we do not
    retry it. Only a :class:`HidppTimeout` (a device that may be asleep) is
    retried up to ``attempts`` times.
    """
    for attempt in range(attempts):
        try:
            transport.get_protocol_version()
            return True
        except HidppError:
            return True  # an error reply still proves the index is present
        except OSError:
            return False  # write rejected; retrying will not help
        except HidppTimeout:
            if attempt + 1 < attempts:
                time.sleep(WAKE_RETRY_DELAY)
            continue
    return False


def _try_match(
    path: str, device_index: int, *, attempts: int = 3
) -> Optional[MX4Device]:
    """Probe ``path``/``device_index`` and return an :class:`MX4Device` on match.

    Returns ``None`` (and leaves no transport open) if the index does not
    respond or is not an MX Master 4. The transport is kept open only on a
    successful match.
    """
    transport: Optional[HidppTransport] = None
    try:
        transport = HidppTransport(path, device_index, timeout=0.5)
        # Liveness ping; an absent index times out. A real but idle MX4 may drop
        # the first request while it wakes, so retry. A broken-pipe write raises
        # _NodeUnwritable (handled by the caller to skip the whole node).
        if not _ping_with_retries(transport, attempts=attempts):
            transport.close()
            return None
        name_index = transport.get_feature(FEATURE_DEVICE_NAME)
        if name_index == 0:
            transport.close()
            return None
        name = read_device_name(transport, name_index)
        if TARGET_NAME.lower() not in name.lower():
            transport.close()
            return None
        haptic_index = transport.get_feature(FEATURE_HAPTIC)
        reprog_index = transport.get_feature(FEATURE_REPROG_CONTROLS_V4)
        logger.info(
            "found %s on %s index %d (haptic=0x%02X reprog=0x%02X)",
            name,
            path,
            device_index,
            haptic_index,
            reprog_index,
        )
        return MX4Device(
            transport=transport,
            path=path,
            device_index=device_index,
            name=name,
            haptic_index=haptic_index,
            reprog_index=reprog_index,
        )
    except (HidppError, HidppTimeout, OSError) as exc:
        logger.debug("no MX4 at %s index %d: %s", path, device_index, exc)
        if transport is not None:
            transport.close()
        return None


def find_mx_master_4() -> MX4Device:
    """Locate the MX Master 4, scanning receivers then falling back to env.

    Order:

    1. ``MX4_HIDRAW`` + ``MX4_DEVICE_INDEX`` if both are set (explicit override).
    2. Scan every Logitech receiver node, indices 1..6, matching the device name.
    3. As a last resort, try the env defaults (or the documented values).

    :raises RuntimeError: if no MX Master 4 can be found.
    """
    env_path = os.environ.get("MX4_HIDRAW")
    env_index_raw = os.environ.get("MX4_DEVICE_INDEX")

    # 1. Explicit override wins (with extra wake retries).
    if env_path and env_index_raw:
        try:
            device = _try_match(env_path, int(env_index_raw, 0), attempts=OVERRIDE_ATTEMPTS)
        except ValueError:
            device = None
        if device is not None:
            return device
        logger.warning(
            "MX4_HIDRAW/MX4_DEVICE_INDEX did not match; falling back to scan"
        )

    # 2. Scan all receiver nodes. Broken-pipe writes (wrong interface / unpaired
    #    index) fail fast; only timeouts (a possibly-sleeping device) are
    #    retried. Consecutive retries on the *same* index are what wake a
    #    deep-sleeping MX4 (each write nudges it). We make a few full scan
    #    passes: an early pass's writes can wake a device that then matches on a
    #    later pass (the cheap broken-pipe nodes keep passes inexpensive).
    nodes = list_receiver_nodes()
    for scan_pass in range(SCAN_PASSES):
        for node in nodes:
            for index in PROBE_DEVICE_INDICES:
                device = _try_match(node, index, attempts=SCAN_ATTEMPTS)
                if device is not None:
                    return device

    # 3. Last-resort env defaults (lets an operator force a node even if the
    #    HID_NAME heuristic missed it).
    if env_path:
        index = int(env_index_raw, 0) if env_index_raw else 2
        device = _try_match(env_path, index, attempts=OVERRIDE_ATTEMPTS)
        if device is not None:
            return device

    raise RuntimeError(
        "MX Master 4 not found. Set MX4_HIDRAW and MX4_DEVICE_INDEX to point "
        "at the receiver's HID++ hidraw node, e.g. MX4_HIDRAW=/dev/hidraw7 "
        "MX4_DEVICE_INDEX=2."
    )
