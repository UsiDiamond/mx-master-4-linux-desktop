"""Raw HID++ 2.0 transport over a ``hidraw`` file descriptor.

This is the only module that touches the wire. It implements just enough of the
HID++ 2.0 protocol to drive the MX Master 4:

* short (``0x10``, 7 bytes) and long (``0x11``, 20 bytes) requests,
* synchronous request/response matched by ``(device_index, feature_index,
  software_id)``,
* a background reader thread that dispatches *unsolicited* notifications to
  registered callbacks,
* feature-index resolution via the ROOT feature (``0x0000``),
* a generic :meth:`HidppTransport.call`.

Framing (verified live on an MX Master 4 behind a Logi Bolt receiver)::

    [report_id, device_index, feature_index, func_byte, p0, p1, p2, ...]

where ``func_byte = (function_id << 4) | software_id`` and we always use
software id ``0x0E``. A reply echoes back the same ``device_index`` /
``feature_index`` / ``software_id``; a notification is an unsolicited report
whose software-id nibble is ``0`` and whose function nibble identifies the
event.
"""

from __future__ import annotations

import logging
import os
import select
import threading
import time
from collections.abc import Callable
from typing import Optional

logger = logging.getLogger(__name__)

# Report ids and lengths (including the leading report-id byte).
SHORT_REPORT_ID = 0x10
LONG_REPORT_ID = 0x11
SHORT_LEN = 7
LONG_LEN = 20

# We tag every request with this software id so we can recognise our own
# replies and tell them apart from notifications (which carry software id 0).
SOFTWARE_ID = 0x0E

# The always-present ROOT feature lives at feature index 0.
ROOT_FEATURE_INDEX = 0x00
ROOT_FN_GET_FEATURE = 0x00
ROOT_FN_GET_PROTOCOL_VERSION = 0x01

# A HID++ error reply uses this synthetic feature index (0xFF) as report 0x10.
HIDPP_ERROR_REPORT_ID = 0x10
HIDPP_ERROR_FEATURE = 0xFF

NotificationCallback = Callable[[bytes], None]


def func_byte(function_id: int, software_id: int = SOFTWARE_ID) -> int:
    """Return the HID++ function byte: ``(function_id << 4) | software_id``.

    ``function_id`` is the *nibble* (e.g. ``0x4`` for the haptic "play"
    function ``0x40``); ``software_id`` defaults to :data:`SOFTWARE_ID`.
    """
    return ((function_id & 0x0F) << 4) | (software_id & 0x0F)


class HidppError(Exception):
    """A HID++ error reply (report ``0x10``, feature ``0xFF``)."""

    def __init__(self, feature_index: int, function_id: int, error_code: int):
        self.feature_index = feature_index
        self.function_id = function_id
        self.error_code = error_code
        super().__init__(
            "HID++ error 0x%02X (feature_index=0x%02X function=0x%X)"
            % (error_code, feature_index, function_id)
        )


class HidppTimeout(Exception):
    """No matching reply arrived within the timeout window."""


class HidppTransport:
    """Thread-safe HID++ 2.0 transport bound to one device on one hidraw node.

    Only one request is in flight at a time (guarded by a lock); the background
    reader thread routes replies to the waiting caller and notifications to the
    registered callbacks. Use as a context manager or call :meth:`close`.
    """

    def __init__(
        self,
        path: str,
        device_index: int,
        *,
        timeout: float = 1.0,
        fd: Optional[int] = None,
    ) -> None:
        """Open ``path`` for read/write and start the reader thread.

        :param path: hidraw node, e.g. ``/dev/hidraw7``.
        :param device_index: HID++ device index of the target (1..6).
        :param timeout: default per-request reply timeout in seconds.
        :param fd: an already-open file descriptor to use instead of opening
            ``path`` (test seam for an in-memory fake hidraw). The transport
            takes ownership and closes it on :meth:`close`.
        """
        self.path = path
        self.device_index = device_index
        self.timeout = timeout

        # O_RDWR so we can both send requests and read replies/notifications.
        self._fd = fd if fd is not None else os.open(path, os.O_RDWR)

        # If any post-open setup fails, close the fd we just opened so it does
        # not leak (e.g. os.pipe() exhaustion or a thread-start failure).
        try:
            # Request serialisation + reply rendezvous.
            self._send_lock = threading.Lock()
            self._reply_lock = threading.Lock()
            self._reply_cond = threading.Condition(self._reply_lock)
            # Most-recent replies keyed by
            # (device_index, feature_index, function_id, software_id).
            self._replies: dict[tuple[int, int, int, int], bytes] = {}
            # Key of the single in-flight request, so error replies (which carry
            # feature index 0xFF) can be routed to the waiting caller, and so
            # late replies for abandoned requests can be discarded.
            self._pending_key: Optional[tuple[int, int, int, int]] = None

            # Notification subscribers keyed by feature index (None = all).
            self._callbacks: dict[Optional[int], list[NotificationCallback]] = {}
            self._callbacks_lock = threading.Lock()

            # Reader thread lifecycle. A self-pipe lets close() wake select().
            self._stop = threading.Event()
            self._wake_r, self._wake_w = os.pipe()
            self._reader = threading.Thread(
                target=self._read_loop, name="hidpp-reader", daemon=True
            )
            self._reader.start()
        except BaseException:
            try:
                os.close(self._fd)
            except OSError:
                pass
            for attr in ("_wake_r", "_wake_w"):
                fd_to_close = getattr(self, attr, None)
                if fd_to_close is not None:
                    try:
                        os.close(fd_to_close)
                    except OSError:
                        pass
            raise
        logger.debug("HidppTransport opened %s device_index=%d", path, device_index)

    # -- context manager -------------------------------------------------
    def __enter__(self) -> "HidppTransport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- notification subscription --------------------------------------
    def add_notification_callback(
        self, callback: NotificationCallback, feature_index: Optional[int] = None
    ) -> None:
        """Register ``callback`` for unsolicited notifications.

        :param feature_index: only deliver notifications whose report's
            feature-index byte matches this value; ``None`` delivers all.
        """
        with self._callbacks_lock:
            self._callbacks.setdefault(feature_index, []).append(callback)

    def remove_notification_callback(
        self, callback: NotificationCallback, feature_index: Optional[int] = None
    ) -> None:
        """Unregister a previously added notification callback (best effort)."""
        with self._callbacks_lock:
            handlers = self._callbacks.get(feature_index)
            if handlers and callback in handlers:
                handlers.remove(callback)

    # -- core request/response ------------------------------------------
    def call(
        self,
        feature_index: int,
        function_id: int,
        *params: int,
        long: bool = False,
        timeout: Optional[float] = None,
    ) -> bytes:
        """Send a request and return the matching reply payload (full report).

        :param feature_index: target feature's runtime index.
        :param function_id: function *nibble* (e.g. ``0x4`` for haptic play).
        :param params: parameter bytes (padded to the report length).
        :param long: send a long (``0x11``, 20-byte) request instead of short.
        :param timeout: override the default reply timeout.
        :returns: the full reply report as ``bytes``.
        :raises HidppError: on a HID++ error reply.
        :raises HidppTimeout: if no matching reply arrives in time.
        """
        report_id = LONG_REPORT_ID if long else SHORT_REPORT_ID
        length = LONG_LEN if long else SHORT_LEN
        fb = func_byte(function_id, SOFTWARE_ID)

        payload = bytearray(length)
        payload[0] = report_id
        payload[1] = self.device_index
        payload[2] = feature_index
        payload[3] = fb
        for i, value in enumerate(params):
            if 4 + i >= length:
                raise ValueError("too many params for a %d-byte report" % length)
            payload[4 + i] = value & 0xFF

        # Key includes the function nibble so two functions on the same feature
        # index (notably ROOT getFeature vs getProtocolVersion) never collide —
        # a late reply to one must not satisfy the other.
        key = (self.device_index, feature_index, function_id & 0x0F, SOFTWARE_ID)
        wait = self.timeout if timeout is None else timeout

        with self._send_lock:
            # Clear any stale reply for this key before sending. Requests are
            # serialised by this lock, so only one is ever in flight; the
            # reader records the pending key so it can route an error reply
            # (which echoes feature index 0xFF, not our feature) back to us.
            with self._reply_lock:
                self._replies.pop(key, None)
                self._pending_key = key
            try:
                os.write(self._fd, bytes(payload))
            except OSError:
                # Clear the pending key so a later reply is not misrouted, then
                # propagate (callers treat OSError as a device/permission fault).
                with self._reply_lock:
                    self._pending_key = None
                raise
            deadline = time.monotonic() + wait
            with self._reply_cond:
                while key not in self._replies:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._pending_key = None
                        raise HidppTimeout(
                            "no reply for feature_index=0x%02X function=0x%X"
                            % (feature_index, function_id)
                        )
                    self._reply_cond.wait(remaining)
                reply = self._replies.pop(key)
                self._pending_key = None

        self._raise_if_error(reply, feature_index, function_id)
        return reply

    def write_raw(self, report: bytes) -> None:
        """Write a fully formed report verbatim (no reply is awaited).

        Used for fire-and-forget commands such as the proven haptic "play"
        packet where we do not need to block on an echo.
        """
        with self._send_lock:
            os.write(self._fd, report)

    @staticmethod
    def _raise_if_error(reply: bytes, feature_index: int, function_id: int) -> None:
        """Raise :class:`HidppError` if ``reply`` is a HID++ error report.

        A HID++ 2.0 error reply has the layout
        ``10 <device_index> ff <feature_index> <function> <error_code>``.
        """
        if (
            len(reply) >= 6
            and reply[0] == HIDPP_ERROR_REPORT_ID
            and reply[2] == HIDPP_ERROR_FEATURE
        ):
            raise HidppError(reply[3], function_id, reply[5])

    # -- feature resolution ---------------------------------------------
    def get_feature(self, feature_id: int) -> int:
        """Resolve a 16-bit feature id to its runtime feature index.

        Calls ROOT ``getFeature`` with the feature id's two bytes; the reply's
        byte at offset 4 is the feature index (``0`` means "not present").
        """
        hi = (feature_id >> 8) & 0xFF
        lo = feature_id & 0xFF
        reply = self.call(ROOT_FEATURE_INDEX, ROOT_FN_GET_FEATURE, hi, lo)
        index = reply[4]
        logger.debug("getFeature 0x%04X -> index 0x%02X", feature_id, index)
        return index

    def get_protocol_version(self) -> tuple[int, int]:
        """Return ``(major, minor)`` of the device's HID++ protocol.

        Also serves as a liveness ping when scanning device indices.
        """
        # Ping marker echoed back in the third param so we can sanity check.
        reply = self.call(
            ROOT_FEATURE_INDEX, ROOT_FN_GET_PROTOCOL_VERSION, 0x00, 0x00, 0x5A
        )
        return reply[4], reply[5]

    # -- reader thread ---------------------------------------------------
    def _read_loop(self) -> None:
        """Background loop: classify each report as a reply or a notification."""
        poll_fds = [self._fd, self._wake_r]
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select(poll_fds, [], [], 0.5)
            except (OSError, ValueError):
                break  # fd closed during shutdown
            if self._wake_r in readable:
                break
            if self._fd not in readable:
                continue
            try:
                data = os.read(self._fd, 64)
            except OSError:
                break
            if not data:
                continue
            self._dispatch(bytes(data))

    def _dispatch(self, report: bytes) -> None:
        """Route ``report`` to a waiting caller or to notification callbacks."""
        if len(report) < 4:
            return
        report_id, device_index = report[0], report[1]
        feature_index, fb = report[2], report[3]
        software_id = fb & 0x0F

        # A HID++ error report (10 .. ff ..) echoes feature index 0xFF rather
        # than our feature, but it DOES carry the offending feature index and
        # function in bytes 3/4. Route it to the in-flight request only if those
        # match the pending key, so a late error for an abandoned request cannot
        # spuriously raise on the next, unrelated call.
        is_error = (
            report_id == HIDPP_ERROR_REPORT_ID and feature_index == HIDPP_ERROR_FEATURE
        )
        if is_error:
            with self._reply_cond:
                pending = self._pending_key
                if pending is not None and len(report) >= 5:
                    err_feature = report[3]
                    err_function = (report[4] >> 4) & 0x0F
                    # pending = (device_index, feature_index, function_id, swid)
                    if err_feature == pending[1] and err_function == pending[2]:
                        self._replies[pending] = report
                        self._reply_cond.notify_all()
                    # else: stale error for an abandoned request — discard.
            return

        # A report carrying our software id is a normal reply. Only accept it if
        # it matches the in-flight request's key: ROOT functions (getFeature,
        # getProtocolVersion, ...) all share key (device, 0, swid), so a *late*
        # reply from a previously timed-out call would otherwise be picked up by
        # the next ROOT call and misread. Dropping non-pending replies makes the
        # transport robust to a device that answers a request after we gave up.
        if software_id == SOFTWARE_ID:
            function_id = (fb >> 4) & 0x0F
            key = (device_index, feature_index, function_id, software_id)
            with self._reply_cond:
                if self._pending_key is not None and key == self._pending_key:
                    self._replies[key] = report
                    self._reply_cond.notify_all()
                # else: stale/late reply for an abandoned request — discard.
            return

        # Otherwise it is an unsolicited notification.
        self._fire_notification(feature_index, report)

    def _fire_notification(self, feature_index: int, report: bytes) -> None:
        """Invoke registered callbacks for a notification report."""
        with self._callbacks_lock:
            handlers = list(self._callbacks.get(feature_index, ()))
            handlers += list(self._callbacks.get(None, ()))
        for handler in handlers:
            try:
                handler(report)
            except Exception:  # noqa: BLE001 - never let a callback kill the reader
                logger.exception("notification callback raised")

    # -- liveness --------------------------------------------------------
    def reader_alive(self) -> bool:
        """Return whether the background reader thread is still running.

        The reader exits when the hidraw fd errors (e.g. the device was
        unplugged). A daemon can poll this to detect a vanished device and shut
        down cleanly instead of running on with a dead transport.
        """
        return self._reader.is_alive() and not self._stop.is_set()

    # -- shutdown --------------------------------------------------------
    def close(self) -> None:
        """Stop the reader thread and close the hidraw fd. Idempotent."""
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass
        if self._reader.is_alive():
            self._reader.join(timeout=2.0)
        for fd in (self._fd, self._wake_r, self._wake_w):
            try:
                os.close(fd)
            except OSError:
                pass
        logger.debug("HidppTransport closed %s", self.path)
