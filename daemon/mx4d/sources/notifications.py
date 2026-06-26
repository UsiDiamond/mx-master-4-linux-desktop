"""Desktop-notification source (``org.freedesktop.Notifications`` ``Notify``).

Works on both KDE Plasma and LXQt because both route desktop notifications
through the freedesktop session-bus service. We do **not** own the
``Notifications`` name (that would steal notifications from the real daemon);
instead we *monitor* the bus like ``dbus-monitor`` via
``org.freedesktop.DBus.Monitoring.BecomeMonitor`` and read each ``Notify``
method call, extracting the app name and the ``urgency`` hint.

If BecomeMonitor is unavailable/awkward, we fall back to spawning
``dbus-monitor`` and parsing its stdout. Either way, the source degrades
gracefully: if neither path works it disables itself.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from typing import Optional

from . import KIND_NOTIFICATION, EmitCallback, Event, Source

logger = logging.getLogger(__name__)

_NOTIFY_MATCH = "type=method_call,interface=org.freedesktop.Notifications,member=Notify"


class NotificationsSource(Source):
    """Emit a notification event for every freedesktop ``Notify`` call."""

    kind = KIND_NOTIFICATION

    def __init__(self) -> None:
        self._emit: Optional[EmitCallback] = None
        self._bus = None
        self._match_added = False
        # Fallback (dbus-monitor subprocess) state.
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def available(self) -> bool:
        """A session bus or the ``dbus-monitor`` binary is enough."""
        return True

    # -- lifecycle -------------------------------------------------------
    def start(self, emit: EmitCallback) -> bool:
        """Try BecomeMonitor first, then the dbus-monitor subprocess fallback."""
        self._emit = emit
        if self._start_become_monitor():
            logger.info("notifications source: monitoring session bus (BecomeMonitor)")
            return True
        if self._start_dbus_monitor_fallback():
            logger.info("notifications source: monitoring via dbus-monitor subprocess")
            return True
        logger.warning("notifications source unavailable; disabled")
        return False

    def stop(self) -> None:
        """Tear down whichever monitoring path is active. Idempotent.

        A python-dbus *monitor* connection (post-BecomeMonitor) is fragile to
        explicit teardown — calling ``remove_message_filter`` / closing it can
        crash libdbus. We instead flip a flag so the filter ignores further
        messages and simply drop our reference; the connection is process-
        private and is reclaimed when the process exits.
        """
        self._stop.set()
        if self._bus is not None:
            # Do NOT remove the filter or close the monitor bus (segfault-prone);
            # the _stop flag below makes _on_message a no-op.
            self._bus = None
            self._match_added = False
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    # -- BecomeMonitor path ---------------------------------------------
    def _start_become_monitor(self) -> bool:
        """Become a passive bus monitor and filter for Notify calls.

        Uses a **private** connection (``private=True``), NOT the shared
        ``SessionBus`` singleton. ``BecomeMonitor`` turns the entire connection
        into a receive-only monitor — it can no longer own bus names or reply to
        method calls — so doing it on the shared bus would silently break the
        daemon's own ``dev.usidiamond.mx4`` service. The private connection
        isolates the monitor from everything else.
        """
        try:
            import dbus  # python-dbus
        except ImportError:
            return False
        try:
            bus = dbus.SessionBus(private=True)
            dbus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
            monitoring = dbus.Interface(dbus_obj, "org.freedesktop.DBus.Monitoring")
            # flags must be 0 per the spec.
            monitoring.BecomeMonitor([_NOTIFY_MATCH], dbus.UInt32(0))
            bus.add_message_filter(self._on_message)
            self._bus = bus
            self._match_added = True
            return True
        except Exception as exc:  # noqa: BLE001 - any failure -> fall back
            logger.debug("BecomeMonitor failed (%s); will try dbus-monitor", exc)
            return False

    def _on_message(self, _bus, message) -> None:
        """python-dbus message filter: handle each monitored ``Notify`` call."""
        if self._stop.is_set():
            return
        try:
            if message.get_member() != "Notify":
                return
            if message.get_interface() != "org.freedesktop.Notifications":
                return
            args = list(message.get_args_list())
            self._emit_from_notify_args(args)
        except Exception:  # noqa: BLE001 - never let the filter raise into dbus
            logger.debug("failed to parse Notify message", exc_info=True)

    def _emit_from_notify_args(self, args: list) -> None:
        """Map ``Notify`` arguments to an :class:`Event`.

        Notify signature: ``susssasa{sv}i`` — app_name, replaces_id, app_icon,
        summary, body, actions, hints, expire_timeout. Urgency is hint byte 0/1/2.
        """
        app_name = str(args[0]) if args else ""
        urgency = 1  # normal
        if len(args) >= 7:
            hints = args[6]
            try:
                if "urgency" in hints:
                    urgency = int(hints["urgency"])
            except (TypeError, ValueError):
                urgency = 1
        if self._emit is not None:
            self._emit(Event(KIND_NOTIFICATION, {"app": app_name, "urgency": urgency}))

    # -- dbus-monitor subprocess fallback -------------------------------
    def _start_dbus_monitor_fallback(self) -> bool:
        """Spawn ``dbus-monitor`` and parse its stdout in a thread."""
        binary = shutil.which("dbus-monitor")
        if binary is None:
            return False
        try:
            self._proc = subprocess.Popen(
                [
                    binary,
                    "--session",
                    "interface=org.freedesktop.Notifications,member=Notify",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            logger.debug("could not spawn dbus-monitor: %s", exc)
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._parse_dbus_monitor, name="notif-dbus-monitor", daemon=True
        )
        self._thread.start()
        return True

    # urgency in dbus-monitor text output appears as: byte 2 (inside the hints).
    _URGENCY_RE = re.compile(r'string "urgency"\s*\n\s*variant\s+byte\s+(\d+)')

    def _parse_dbus_monitor(self) -> None:
        """Read dbus-monitor stdout, emitting one event per Notify block."""
        assert self._proc is not None and self._proc.stdout is not None
        block: list[str] = []
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            if line.startswith("method call"):
                # New message starts; flush any prior Notify block.
                self._flush_block(block)
                block = [line]
            else:
                block.append(line)
        self._flush_block(block)

    def _flush_block(self, block: list[str]) -> None:
        """Emit an event if a buffered dbus-monitor block is a Notify call."""
        if not block:
            return
        text = "".join(block)
        if "member=Notify" not in text and "Notify" not in text:
            return
        if "org.freedesktop.Notifications" not in text:
            return
        urgency = 1
        match = self._URGENCY_RE.search(text)
        if match:
            try:
                urgency = int(match.group(1))
            except ValueError:
                urgency = 1
        if self._emit is not None:
            self._emit(Event(KIND_NOTIFICATION, {"app": "", "urgency": urgency}))
        block.clear()
