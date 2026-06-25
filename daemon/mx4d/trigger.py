"""TriggerWatcher — capture the MX Master 4 "Actions Ring" haptic panel.

The haptic touch panel surfaces in REPROG CONTROLS V4 (feature ``0x1B04``) as
control id (CID) ``0x01A0``. By default it performs its on-device task; we
**divert** it via ``setCidReporting`` so that, instead, each press/release is
delivered to us as a ``0x1B04`` ``divertedButtonsEvent`` notification (function
``0x00``). The notification payload carries up to four 16-bit currently-pressed
CIDs; ``0x0000`` means none. A press is "our CID appeared", a release is "our
CID disappeared".

When the control additionally has **raw-XY reporting** enabled (it is then in
Solaar's "Mouse Gestures" mode, i.e. ``divert-keys = 2``), the firmware ALSO
emits a ``divertedRawXYEvent`` (function ``0x01``) on every sensor movement
while the control is held. Its payload is two signed big-endian 16-bit
displacements ``dx``/``dy`` beginning at report offset 4. We surface these to
``on_raw_xy`` so the daemon can drive a flick/scrub interaction. We never enable
raw-XY ourselves under Solaar (a confirmed write broken-pipes and a
fire-and-forget one does not stick on this firmware); Solaar owns that setting
and the kernel broadcasts the events to our hidraw reader just like the button
events, so we read them passively.

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

# Default press-and-hold threshold (seconds). A press released sooner than this
# is a "tap"; one held at least this long is a "hold". Tuned so a deliberate
# hold is unambiguous without making a normal tap feel laggy.
HOLD_THRESHOLD_DEFAULT = 0.4

# REPROG CONTROLS V4 (0x1B04) function ids (function nibble).
REPROG_FN_GET_COUNT = 0x0
REPROG_FN_GET_CID_INFO = 0x1
REPROG_FN_SET_CID_REPORTING = 0x3
# Event notifications are broadcasts whose software-id nibble is 0; the function
# nibble distinguishes them: 0x00 = divertedButtonsEvent (press/release),
# 0x01 = divertedRawXYEvent (sensor movement while a raw-XY key is held).
REPROG_EVENT_DIVERTED_BUTTONS = 0x00
REPROG_EVENT_DIVERTED_RAW_XY = 0x01

# The MX Master 4 haptic "Actions Ring" panel control id.
ACTIONS_RING_CID = 0x01A0

# setCidReporting flag bits (flags byte 1).
_FLAG_DIVERT = 1 << 1
_FLAG_REMAP_VALID = 1 << 4
_FLAG_DIVERT_VALID = 1 << 5

PressCallback = Callable[[int], None]
# Called with (dx, dy) on each divertedRawXYEvent while the panel is held.
RawXYCallback = Callable[[int, int], None]


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


def parse_raw_xy(report: bytes) -> tuple[int, int]:
    """Extract ``(dx, dy)`` from a divertedRawXYEvent report.

    The payload is two signed big-endian 16-bit displacements starting at report
    offset 4 (``struct.unpack("!hh", report[4:8])`` in Solaar's reference
    decoder). A short/garbled report yields ``(0, 0)`` rather than raising, so a
    bad packet can never kill the reader thread.
    """
    if len(report) < 8:
        return (0, 0)
    dx = int.from_bytes(report[4:6], "big", signed=True)
    dy = int.from_bytes(report[6:8], "big", signed=True)
    return (dx, dy)


class TriggerWatcher:
    """Diverts the Actions Ring panel and reports its presses/releases."""

    def __init__(
        self,
        transport: HidppTransport,
        reprog_index: int,
        *,
        cid: int = ACTIONS_RING_CID,
        divert: bool = True,
        confirm: bool = True,
        listen: bool = False,
        hold_threshold: float = HOLD_THRESHOLD_DEFAULT,
        on_press: Optional[PressCallback] = None,
        on_tap: Optional[PressCallback] = None,
        on_hold: Optional[PressCallback] = None,
        on_release: Optional[PressCallback] = None,
        on_raw_xy: Optional[RawXYCallback] = None,
    ) -> None:
        """Configure the watcher (call :meth:`start` to actually divert).

        :param transport: an open transport for the device.
        :param reprog_index: runtime feature index of ``0x1B04``.
        :param cid: the control id to capture (default the Actions Ring panel).
        :param divert: if ``True``, divert the control so its presses arrive as
            HID++ notifications. Maps to config key ``trigger.divert_panel``.
        :param confirm: if ``True`` the (un)divert is a request/response that
            awaits the device's reply (standalone). If ``False`` it is sent
            fire-and-forget via a raw write — used in Solaar coexist mode, where
            a request/response would get a broken pipe but a write still lands,
            so we can still capture the panel without contending with Solaar.
        :param listen: if ``True`` (and ``divert`` is ``False``) subscribe to the
            control's notifications WITHOUT diverting it — for the case where
            something else (Solaar) has already diverted the panel and we only
            want to read the broadcast press/release events.
        :param hold_threshold: seconds a press must be held to count as a hold
            rather than a tap (see :data:`HOLD_THRESHOLD_DEFAULT`).
        :param on_press: called with the CID on every press (gesture start).
        :param on_tap: called with the CID on release IF the press was a short
            tap (held less than ``hold_threshold``).
        :param on_hold: called with the CID once a press is held at least
            ``hold_threshold`` (fires while still held, before release).
        :param on_release: called with the CID on every release (gesture end).
        :param on_raw_xy: called with ``(dx, dy)`` on each divertedRawXYEvent
            while the panel is held — only ever fires when raw-XY reporting is
            enabled on the control (Solaar "Mouse Gestures" mode). Inert
            otherwise, so wiring it is free when the feature is off.
        """
        self.transport = transport
        self.reprog_index = reprog_index
        self.cid = cid
        self.divert = divert
        self.confirm = confirm
        self.listen = listen
        self.hold_threshold = hold_threshold
        self.on_press = on_press
        self.on_tap = on_tap
        self.on_hold = on_hold
        self.on_release = on_release
        self.on_raw_xy = on_raw_xy

        self._pressed = False
        self._held = False
        self._hold_timer: Optional[threading.Timer] = None
        self._started = False
        self._lock = threading.Lock()
        self._atexit_registered = False

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        """Begin capturing the control: optionally divert it, then subscribe.

        :returns: ``True`` if the watcher is now listening, ``False`` if it has
            nothing to do (neither diverting nor listening) or a confirmed
            divert was rejected by the device (logged, non-fatal).
        """
        if not self.divert and not self.listen:
            logger.info("trigger disabled by config; panel left native")
            return False
        with self._lock:
            if self._started:
                return True
            if self.divert and not self._set_divert(True):
                return False
            # Subscribe whether we diverted (standalone / coexist-write) or are
            # only listening to a divert another process (Solaar) set up.
            self.transport.add_notification_callback(
                self._on_notification, self.reprog_index
            )
            self._started = True
            if self.divert and not self._atexit_registered:
                # Only register the restore hook when WE did the diverting.
                atexit.register(self.stop)
                self._atexit_registered = True
            if self.divert:
                logger.info(
                    "capturing Actions Ring CID 0x%04X (%s)",
                    self.cid,
                    "confirmed" if self.confirm else "fire-and-forget coexist",
                )
            else:
                logger.info(
                    "listening for Actions Ring CID 0x%04X (passive; another "
                    "process owns the divert)",
                    self.cid,
                )
            return True

    def _set_divert(self, divert: bool) -> bool:
        """Send setCidReporting to (un)divert the control.

        Confirmed mode awaits the device reply and reports failure. Coexist mode
        sends the packet fire-and-forget (no reply awaited), so it lands without
        contending with a running Solaar's request/response traffic.
        """
        params = build_set_cid_reporting_params(self.cid, divert=divert)
        if self.confirm:
            try:
                self.transport.call(
                    self.reprog_index,
                    REPROG_FN_SET_CID_REPORTING,
                    *params,
                    long=True,
                )
                return True
            except (HidppError, HidppTimeout, OSError) as exc:
                logger.error(
                    "failed to %sdivert CID 0x%04X: %s",
                    "" if divert else "un-",
                    self.cid,
                    exc,
                )
                return False
        try:
            self.transport.write_raw(self._divert_packet(params))
            return True
        except OSError as exc:
            logger.error(
                "failed to write %sdivert for CID 0x%04X: %s",
                "" if divert else "un-",
                self.cid,
                exc,
            )
            return False

    def _divert_packet(self, params: list[int]) -> bytes:
        """Build the long ``setCidReporting`` report for a fire-and-forget write."""
        header = [
            LONG_REPORT_ID,
            self.transport.device_index,
            self.reprog_index,
            func_byte(REPROG_FN_SET_CID_REPORTING),
        ]
        return bytes(header + params).ljust(LONG_LEN, b"\x00")[:LONG_LEN]

    def stop(self) -> None:
        """Stop capturing and, if WE diverted, restore the control. Idempotent.

        Cancels any pending hold timer and unsubscribes first. A listen-only
        watcher never diverted, so it has nothing to restore. When we did
        divert: confirmed mode retries the restore a few times then falls back
        to a fire-and-forget write; coexist mode is fire-and-forget from the
        start. Leaving the user's mouse clean is the priority.
        """
        with self._lock:
            if not self._started:
                return
            self._started = False
            self._cancel_hold_timer()
            self.transport.remove_notification_callback(
                self._on_notification, self.reprog_index
            )
            if not self.divert:
                return  # listen-only: we never diverted, nothing to restore

            params = build_set_cid_reporting_params(self.cid, divert=False)
            if self.confirm:
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
            # Last resort (or coexist default): write the restore without a reply.
            try:
                self.transport.write_raw(self._divert_packet(params))
                logger.info(
                    "restored CID 0x%04X to non-diverted (fire-and-forget)",
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
        """Route a 0x1B04 notification to the button or raw-XY handler.

        The reader thread already filtered to our feature index. A notification
        carries software-id nibble 0; its function nibble then picks the event:
        ``0x0`` = divertedButtonsEvent (press/release), ``0x1`` =
        divertedRawXYEvent (movement). Anything else is ignored.
        """
        if len(report) < 4:
            return
        func_nibble = report[3]
        if (func_nibble & 0x0F) != 0:
            return  # a reply with a software id, not a notification
        event = (func_nibble >> 4) & 0x0F
        if event == REPROG_EVENT_DIVERTED_BUTTONS:
            self._on_buttons_event(report)
        elif event == REPROG_EVENT_DIVERTED_RAW_XY:
            self._on_raw_xy_event(report)

    def _on_buttons_event(self, report: bytes) -> None:
        """Translate a divertedButtonsEvent into press/tap/hold/release."""
        pressed_cids = parse_pressed_cids(report)
        now_pressed = self.cid in pressed_cids
        if now_pressed and not self._pressed:
            self._on_press()
        elif not now_pressed and self._pressed:
            self._on_release()

    def _on_raw_xy_event(self, report: bytes) -> None:
        """Forward a divertedRawXYEvent's ``(dx, dy)`` while the panel is held.

        The firmware only emits these while a raw-XY-enabled control is down, but
        we gate on our own ``_pressed`` state too so a stray event outside a press
        (or for a different held control) is never delivered. A zero displacement
        is dropped — it carries no direction and only happens at the edges.
        """
        if not self._pressed or self.on_raw_xy is None:
            return
        dx, dy = parse_raw_xy(report)
        if dx == 0 and dy == 0:
            return
        self.on_raw_xy(dx, dy)

    def _on_press(self) -> None:
        """Panel went down: fire on_press and arm the hold timer."""
        self._pressed = True
        self._held = False
        logger.debug("Actions Ring pressed")
        if self.on_press is not None:
            self.on_press(self.cid)
        self._start_hold_timer()

    def _on_release(self) -> None:
        """Panel came up: a press shorter than the hold threshold is a tap."""
        self._pressed = False
        self._cancel_hold_timer()
        was_hold = self._held
        self._held = False
        logger.debug("Actions Ring released (was_hold=%s)", was_hold)
        # A tap fires only if the press never crossed the hold threshold.
        if not was_hold and self.on_tap is not None:
            self.on_tap(self.cid)
        if self.on_release is not None:
            self.on_release(self.cid)

    # -- hold timer ------------------------------------------------------
    def _start_hold_timer(self) -> None:
        """Arm a one-shot timer that fires on_hold if the press is held."""
        self._cancel_hold_timer()
        if self.on_hold is None or self.hold_threshold <= 0:
            return
        timer = threading.Timer(self.hold_threshold, self._fire_hold)
        timer.daemon = True
        self._hold_timer = timer
        timer.start()

    def _cancel_hold_timer(self) -> None:
        """Cancel a pending hold timer (no-op if none is armed)."""
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _fire_hold(self) -> None:
        """Hold threshold reached (runs on the Timer thread).

        Fires only if the panel is still down and we have not already reported a
        hold for this press — a release cancels the timer, but this guards the
        race where the timer fires just as the release arrives.
        """
        if not self._pressed or self._held:
            return
        self._held = True
        logger.debug("Actions Ring held (CID 0x%04X)", self.cid)
        if self.on_hold is not None:
            self.on_hold(self.cid)
