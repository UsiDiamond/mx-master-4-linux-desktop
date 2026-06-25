"""TriggerWatcher — capture the MX Master 4 "Actions Ring" haptic panel.

The haptic touch panel surfaces in REPROG CONTROLS V4 (feature ``0x1B04``) as
control id (CID) ``0x01A0``. By default it performs its on-device task; we
**divert** it via ``setCidReporting`` so that, instead, each press/release is
delivered to us as a ``0x1B04`` ``divertedButtonsEvent`` notification (function
``0x00``). The notification payload carries up to four 16-bit currently-pressed
CIDs; ``0x0000`` means none. A press is "our CID appeared", a release is "our
CID disappeared".

We **always** restore the control to non-diverted on shutdown (stop(), atexit,
and a signal handler installed by the daemon) so the user's mouse is left clean.

setCidReporting (function ``0x30``) parameter layout — HID++ 2.0 ``0x1B04`` /
Solaar ``ReprogrammableKeyV4`` semantics::

    p0 p1  CID (big-endian)
    p2     flags byte 1, bit layout:
             bit0  remap to a different CID (set with valid bit)
             bit1  divert        (route presses to HID++ notifications)
             bit2  persist divert across power cycles
             bit3  (reserved)
             bit4  remap-valid   ("update bit 0")
             bit5  divert-valid  ("update bit 1")
             bit6  persist-valid ("update bit 2")
    p3 p4  remap target CID (big-endian; 0 when not remapping)
    p5     flags byte 2 (raw-XY / force-raw etc.) — left 0 here

To *set* the divert bit we send the divert bit (bit1) together with its valid
mask (bit5); to *clear* it we send the valid mask with the divert bit low.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from typing import Optional

from .hidpp import (
    LONG_LEN,
    LONG_REPORT_ID,
    HidppError,
    HidppTimeout,
    HidppTransport,
    func_byte,
)

logger = logging.getLogger(__name__)

# How many confirmed restore attempts before falling back to fire-and-forget.
RESTORE_ATTEMPTS = 3

# REPROG CONTROLS V4 (0x1B04) function ids (function nibble).
REPROG_FN_GET_COUNT = 0x0
REPROG_FN_GET_CID_INFO = 0x1
REPROG_FN_SET_CID_REPORTING = 0x3
# divertedButtonsEvent is the function-0x00 broadcast notification.
REPROG_EVENT_DIVERTED_BUTTONS = 0x00

# The MX Master 4 haptic "Actions Ring" panel control id.
ACTIONS_RING_CID = 0x01A0

# setCidReporting flag bits (flags byte 1).
_FLAG_DIVERT = 1 << 1
_FLAG_REMAP_VALID = 1 << 4
_FLAG_DIVERT_VALID = 1 << 5

PressCallback = Callable[[int], None]


def build_set_cid_reporting_params(cid: int, divert: bool) -> list[int]:
    """Return the 6 ``setCidReporting`` param bytes to (un)divert ``cid``.

    Sends the divert bit together with its valid/update mask so the device
    applies exactly that change and leaves remap/persist untouched.
    """
    flags = _FLAG_DIVERT_VALID  # we are updating the divert bit...
    if divert:
        flags |= _FLAG_DIVERT  # ...to "on".
    return [
        (cid >> 8) & 0xFF,
        cid & 0xFF,
        flags,
        0x00,  # remap target CID hi (unused)
        0x00,  # remap target CID lo (unused)
        0x00,  # flags byte 2 (raw-XY etc.) untouched
    ]


def parse_pressed_cids(report: bytes) -> list[int]:
    """Extract the pressed CIDs from a divertedButtonsEvent report.

    The payload begins at report offset 4 and holds up to four big-endian
    16-bit CIDs; ``0x0000`` terminates / means "none".
    """
    pressed: list[int] = []
    for i in range(4):
        base = 4 + i * 2
        if base + 1 >= len(report):
            break
        cid = (report[base] << 8) | report[base + 1]
        if cid == 0x0000:
            break
        pressed.append(cid)
    return pressed


class TriggerWatcher:
    """Diverts the Actions Ring panel and reports its presses/releases."""

    def __init__(
        self,
        transport: HidppTransport,
        reprog_index: int,
        *,
        cid: int = ACTIONS_RING_CID,
        divert: bool = True,
        on_press: Optional[PressCallback] = None,
        on_release: Optional[PressCallback] = None,
    ) -> None:
        """Configure the watcher (call :meth:`start` to actually divert).

        :param transport: an open transport for the device.
        :param reprog_index: runtime feature index of ``0x1B04``.
        :param cid: the control id to capture (default the Actions Ring panel).
        :param divert: if ``False``, do not divert (the panel keeps its default
            behaviour); the watcher then does nothing. Maps to config key
            ``trigger.divert_panel``.
        :param on_press: called with the CID when the panel is pressed.
        :param on_release: called with the CID when the panel is released.
        """
        self.transport = transport
        self.reprog_index = reprog_index
        self.cid = cid
        self.divert = divert
        self.on_press = on_press
        self.on_release = on_release

        self._pressed = False
        self._started = False
        self._lock = threading.Lock()
        self._atexit_registered = False

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        """Divert the control and subscribe to its notifications.

        :returns: ``True`` if diversion was enabled, ``False`` if disabled by
            config or if the device rejected the request (logged, non-fatal).
        """
        if not self.divert:
            logger.info("trigger diversion disabled by config; panel left native")
            return False
        with self._lock:
            if self._started:
                return True
            try:
                params = build_set_cid_reporting_params(self.cid, divert=True)
                self.transport.call(
                    self.reprog_index,
                    REPROG_FN_SET_CID_REPORTING,
                    *params,
                    long=True,
                )
            except (HidppError, HidppTimeout, OSError) as exc:
                logger.error("failed to divert CID 0x%04X: %s", self.cid, exc)
                return False
            self.transport.add_notification_callback(
                self._on_notification, self.reprog_index
            )
            self._started = True
            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True
            logger.info("diverted Actions Ring CID 0x%04X for capture", self.cid)
            return True

    def stop(self) -> None:
        """Restore the control to non-diverted. Idempotent; safe in finally.

        Retries the restore a few times (the device can be momentarily
        unresponsive) and, as a last resort, sends the restore packet
        fire-and-forget so the write lands even if no reply comes back — leaving
        the user's mouse clean is the priority.
        """
        with self._lock:
            if not self._started:
                return
            self._started = False
            self.transport.remove_notification_callback(
                self._on_notification, self.reprog_index
            )
            params = build_set_cid_reporting_params(self.cid, divert=False)
            for attempt in range(RESTORE_ATTEMPTS):
                try:
                    self.transport.call(
                        self.reprog_index,
                        REPROG_FN_SET_CID_REPORTING,
                        *params,
                        long=True,
                    )
                    logger.info("restored CID 0x%04X to non-diverted", self.cid)
                    return
                except (HidppError, HidppTimeout, OSError) as exc:
                    logger.debug(
                        "restore attempt %d for CID 0x%04X failed: %s",
                        attempt + 1,
                        self.cid,
                        exc,
                    )
            # Last resort: blast the restore packet without awaiting a reply.
            try:
                header = [
                    LONG_REPORT_ID,
                    self.transport.device_index,
                    self.reprog_index,
                    func_byte(REPROG_FN_SET_CID_REPORTING),
                ]
                packet = bytes(header + params).ljust(LONG_LEN, b"\x00")[:LONG_LEN]
                self.transport.write_raw(packet)
                logger.warning(
                    "restored CID 0x%04X via fire-and-forget (no reply confirmed)",
                    self.cid,
                )
            except OSError as exc:
                logger.error(
                    "FAILED to restore CID 0x%04X (mouse may stay diverted): %s",
                    self.cid,
                    exc,
                )

    # -- notification handling ------------------------------------------
    def _on_notification(self, report: bytes) -> None:
        """Translate a divertedButtonsEvent into press/release callbacks."""
        # Only the function-0x00 broadcast (software-id nibble 0) is a button
        # event; the reader thread already filtered to our feature index.
        if len(report) < 4:
            return
        if (report[3] & 0x0F) != 0:
            return  # a reply with a software id, not a notification
        pressed_cids = parse_pressed_cids(report)
        now_pressed = self.cid in pressed_cids
        if now_pressed and not self._pressed:
            self._pressed = True
            logger.debug("Actions Ring pressed")
            if self.on_press is not None:
                self.on_press(self.cid)
        elif not now_pressed and self._pressed:
            self._pressed = False
            logger.debug("Actions Ring released")
            if self.on_release is not None:
                self.on_release(self.cid)
