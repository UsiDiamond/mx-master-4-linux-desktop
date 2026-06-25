"""The mx4 daemon: wires device + haptics + trigger + sources under a mainloop.

Run via ``python -m mx4d``. It:

* finds the MX Master 4 and resolves its feature indices,
* maps ambient source events to per-source haptic waveforms (honoring the
  master enable, per-source enable, debounce and a quiet-hours toggle),
* on an Actions-Ring press logs "menu requested", plays the configured trigger
  haptic (default ``HAPPY_ALERT`` — ``COMPLETED`` is not supported by the
  observed MX4 firmware), raises the radial overlay (lazily launching it via
  :class:`~mx4d.overlay.OverlayController`), and emits a D-Bus
  ``TriggerPressed`` signal,
* exposes a session D-Bus object ``dev.usidiamond.mx4`` with methods
  ``PlayHaptic(s)`` / ``SetLevel(i)`` / ``ShowMenu(s)`` / ``GetCapabilities()`` /
  ``FocusChanged(s)`` and signals ``TriggerPressed`` / ``TriggerReleased`` /
  ``DeviceLost``.

All blocking HID I/O runs on a dedicated device-I/O worker thread (never on the
GLib/dbus mainloop), and all overlay/D-Bus work is marshalled onto the mainloop
thread, so neither side can ever stall the other.
"""

from __future__ import annotations

import logging
import queue
import signal
import threading
from typing import Optional

from .config import DIVERT_AUTO, DIVERT_TRUE, Mx4Config, load_config
from .device import MX4Device, find_mx_master_4
from .haptics import HapticEngine
from .overlay import OverlayController
from .solaar import solaar_running
from .sources import (
    KIND_FOCUS,
    KIND_NOTIFICATION,
    Event,
    Source,
)
from .sources.focus import FocusSource
from .sources.notifications import NotificationsSource
from .sources.sounds import SoundsSource
from .trigger import TriggerWatcher

logger = logging.getLogger(__name__)

# D-Bus identity (session bus).
DBUS_BUS_NAME = "dev.usidiamond.mx4"
DBUS_OBJECT_PATH = "/dev/usidiamond/mx4"
DBUS_INTERFACE = "dev.usidiamond.mx4.Daemon"

# Critical-urgency notifications upgrade to this stronger waveform. It MUST be a
# distinct, broadly-supported waveform so urgency is felt even when per-source
# intensity differentiation is unavailable on a given firmware: SHARP_COLLISION
# (0x02) is in the observed MX4 mask 0x0001003C, whereas ANGRY_ALERT (0x06) is
# not and would gate down to the same buzz as a normal notification.
CRITICAL_WAVEFORM = "SHARP_COLLISION"

# Sentinel queued to make the device-I/O worker exit.
_STOP = object()


class Mx4Daemon:
    """Owns the device, engine, trigger and sources for the process lifetime."""

    def __init__(
        self,
        *,
        config: Optional[Mx4Config] = None,
        enable_trigger: bool = True,
    ) -> None:
        self.config = config or load_config()
        self.enable_trigger = enable_trigger
        self.device: Optional[MX4Device] = None
        self.haptics: Optional[HapticEngine] = None
        self.trigger: Optional[TriggerWatcher] = None
        self.sources: list[Source] = []
        self._dbus_service = None
        self._overlay: Optional[OverlayController] = None
        self._mainloop = None
        self._shutdown_done = False
        # True when Solaar owns the device: we skip all HID++ request/response
        # (detection, capability read, set_level) and do writes-only haptics.
        self._coexist = False

        # Device-I/O worker: ALL haptic writes (which may block on a HID++
        # round-trip) run here, never on the GLib/dbus mainloop thread. The
        # queue has a small bound so a notification storm coalesces instead of
        # queueing unbounded work; the worker also caches the last level it set
        # so it never re-issues an identical (blocking) set_level.
        self._io_queue: "queue.Queue[object]" = queue.Queue(maxsize=64)
        self._io_thread: Optional[threading.Thread] = None
        self._last_level: Optional[int] = None
        # Set when the device is detected to have gone away mid-run, so the
        # mainloop can shut down cleanly instead of becoming a no-op zombie.
        self._device_lost = threading.Event()

    # -- setup -----------------------------------------------------------
    def setup(self) -> None:
        """Find the device, build the engine, trigger and sources."""
        # Resolve (and LOG) the Solaar-defer / capture decision BEFORE opening the
        # device. The decision is purely process-based (Solaar detection) and so
        # is device-independent; resolving it first means the "Solaar detected ->
        # deferring" log line always appears even if the MX4 is deeply asleep and
        # the subsequent device probe blocks/retries.
        divert = self._resolve_divert() if self.enable_trigger else False

        # Coexist when Solaar is running and we are not forced standalone. Solaar
        # holds the receiver as the HID++ software, so our request/response probes
        # would get a broken pipe; we skip them and do writes-only haptics.
        self._coexist = self.config.divert_panel != DIVERT_TRUE and solaar_running()
        if self._coexist:
            import os

            from .device import (
                KNOWN_CAPABILITY_MASK,
                KNOWN_DEVICE_INDEX,
                KNOWN_HAPTIC_INDEX,
                KNOWN_REPROG_INDEX,
                find_mx_master_4_coexist,
            )

            def _envint(name: str, default: int) -> int:
                raw = os.environ.get(name)
                return int(raw, 0) if raw else default

            self.device = find_mx_master_4_coexist(
                device_index=_envint("MX4_DEVICE_INDEX", KNOWN_DEVICE_INDEX),
                haptic_index=_envint("MX4_HAPTIC_INDEX", KNOWN_HAPTIC_INDEX),
                reprog_index=_envint("MX4_REPROG_INDEX", KNOWN_REPROG_INDEX),
                hidraw=os.environ.get("MX4_HIDRAW"),
            )
            mask = _envint("MX4_CAPABILITY_MASK", KNOWN_CAPABILITY_MASK)
            self.haptics = HapticEngine(
                self.device.transport,
                self.device.haptic_index,
                min_interval=self.config.debounce_interval,
                preset_capabilities=mask,
            )
            logger.info(
                "Solaar coexist: skipped HID++ detection + capability read "
                "(preset mask 0x%08X); haptics writes-only, Solaar owns settings "
                "+ trigger",
                mask,
            )
        else:
            self.device = find_mx_master_4()
            self.haptics = HapticEngine(
                self.device.transport,
                self.device.haptic_index,
                min_interval=self.config.debounce_interval,
            )
            # Read capabilities once up front (cached; gates all plays).
            self.haptics.read_capabilities()

        if self.enable_trigger:
            self.trigger = TriggerWatcher(
                self.device.transport,
                self.device.reprog_index,
                divert=divert,
                on_press=self._on_trigger_press,
                on_release=self._on_trigger_release,
            )

        # Build ambient sources gated by their per-source enable.
        self._build_sources()

    def _resolve_divert(self) -> bool:
        """Resolve the tri-state ``[trigger] divert_panel`` to an effective bool.

        * ``true``  -> divert + capture ourselves (standalone, forced).
        * ``false`` -> never divert (Solaar-first, forced; Solaar's rule fires
          ShowMenu). The daemon still does haptics + ambient + overlay.
        * ``auto``  -> defer to Solaar if a Solaar background process is running
          (do NOT divert — no contention), else capture ourselves (standalone).

        The daemon does haptics + ambient + ShowMenu + overlay in ALL cases; only
        the *trigger* diversion is gated here. We never divert when deferring.
        """
        mode = self.config.divert_panel
        if mode == DIVERT_TRUE:
            return True
        if mode == DIVERT_AUTO and solaar_running():
            logger.info(
                "Solaar detected -> deferring the Actions Ring trigger to Solaar "
                "(ensure the Solaar rule is set up: run "
                "packaging/solaar/setup-solaar.sh or add it in Solaar's Rule "
                "Editor)"
            )
            return False
        if mode == DIVERT_AUTO:
            logger.info(
                "no Solaar detected -> capturing the Actions Ring panel "
                "ourselves (standalone)"
            )
            return True
        # mode == DIVERT_FALSE
        logger.info(
            "trigger.divert_panel=false -> leaving the Actions Ring panel to "
            "Solaar (the daemon provides haptics + overlay only)"
        )
        return False

    def _build_sources(self) -> None:
        candidates: list[Source] = [
            NotificationsSource(),
            FocusSource(),
            SoundsSource(),
        ]
        for src in candidates:
            cfg = self.config.sources.get(src.kind)
            if cfg is None or not cfg.enabled:
                logger.info("source %s disabled by config", src.kind)
                continue
            if not src.available():
                logger.info("source %s unavailable on this system; skipping", src.kind)
                continue
            self.sources.append(src)

    # -- event mapping ---------------------------------------------------
    def on_event(self, event: Event) -> None:
        """Map an ambient :class:`Event` to a haptic play (with all gating).

        Runs on the *source* thread (often the GLib/dbus mainloop thread for the
        notifications monitor), so it must NEVER block on device I/O. We do all
        the cheap gating here and apply the debounce up front — a debounced event
        does zero HID I/O — then hand the (waveform, intensity) to the device-I/O
        worker thread, which performs the blocking HID++ writes.
        """
        if not self.config.ambient_enabled:
            return
        if self.config.quiet_hours_enabled:
            logger.debug("quiet hours on; suppressing %s event", event.kind)
            return
        cfg = self.config.sources.get(event.kind)
        if cfg is None or not cfg.enabled or self.haptics is None:
            return

        # Apply the debounce HERE (before any I/O): a coalesced burst drops
        # entirely instead of issuing one HID round-trip (set_level) per event.
        if not self.haptics.should_play():
            logger.debug("debounced %s event", event.kind)
            return

        waveform = cfg.waveform
        # Critical-urgency notifications get a distinct, stronger waveform.
        if event.kind == KIND_NOTIFICATION and int(event.meta.get("urgency", 1)) >= 2:
            waveform = CRITICAL_WAVEFORM

        # Hand off to the device-I/O worker (non-blocking). If the queue is full
        # (a sustained storm) we simply drop this event — the motor is already
        # busy and coalescing is exactly the desired behaviour.
        try:
            self._io_queue.put_nowait(("play", waveform, int(cfg.intensity)))
        except queue.Full:
            logger.debug("io queue full; dropping %s event", event.kind)

    # -- device-I/O worker ----------------------------------------------
    def _io_worker(self) -> None:
        """Single thread that owns ALL haptic device writes.

        Keeping every blocking HID++ round-trip here means a slow/idle device
        can never stall the GLib/dbus mainloop or a source thread. The level is
        cached so an unchanged intensity never re-issues a (blocking) set_level.
        """
        while True:
            item = self._io_queue.get()
            if item is _STOP:
                return
            if self.haptics is None:
                continue
            try:
                kind = item[0]
                if kind == "play":
                    _, waveform, intensity = item
                    self._apply_level(intensity)
                    self.haptics.play(waveform, force=True)
                elif kind == "force_play":
                    _, waveform = item
                    self.haptics.play(waveform, force=True)
                elif kind == "set_level":
                    _, level = item
                    self._apply_level(level, force=True)
            except OSError as exc:
                # A write/read failure here usually means the device went away.
                logger.error("device I/O failed: %s", exc)
                self._note_device_lost()
            except Exception:  # noqa: BLE001 - worker must never die on one event
                logger.debug("haptic I/O error", exc_info=True)

    def _apply_level(self, level: int, *, force: bool = False) -> None:
        """Set the device level only when it actually changes (cached).

        ``set_level`` is a blocking HID++ round-trip; caching avoids re-issuing
        it for every event and avoids perturbing the motor with redundant writes.
        Failures are logged at debug WITHOUT a traceback so the log is not
        spammed on the hot path.
        """
        if self._coexist:
            # set_level is a HID++ round-trip; under Solaar it would contend.
            # Solaar owns the level here — skip and let plays use it as-is.
            return
        level = max(0, min(100, int(level)))
        if not force and self._last_level == level:
            return
        if self.haptics is None:
            return
        try:
            self.haptics.set_level(level)
            self._last_level = level
        except OSError:
            raise  # surfaced as device-lost by the caller
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not set haptic level to %d: %s", level, exc)

    def _note_device_lost(self) -> None:
        """Flag the device as gone and ask the mainloop to shut down cleanly."""
        if self._device_lost.is_set():
            return
        self._device_lost.set()
        logger.error("MX Master 4 appears to be gone; shutting down")
        if self._dbus_service is not None:
            try:
                self._dbus_service.DeviceLost()
            except Exception:  # noqa: BLE001
                pass
        if self._mainloop is not None:
            self._mainloop.quit()

    # -- trigger ---------------------------------------------------------
    def _on_trigger_press(self, cid: int) -> None:
        """Handle an Actions-Ring press: log, buzz, raise overlay, emit signal.

        This callback runs on the HID *reader* thread, NOT the GLib/dbus
        mainloop thread. dbus-python and the OverlayController's GLib-timeout
        machinery expect to be touched only from the mainloop thread, so we
        marshal the overlay-show + the D-Bus signal onto the mainloop via
        ``GLib.idle_add`` rather than calling them inline here. The buzz is
        dispatched to the (thread-safe) device-I/O worker, so this callback
        never blocks on a haptic write either.
        """
        logger.info("menu requested (Actions Ring CID 0x%04X)", cid)
        if self.haptics is not None:
            try:
                self._io_queue.put_nowait(("force_play", self.config.trigger_waveform))
            except queue.Full:
                logger.debug("io queue full; dropping trigger buzz")
        # Marshal overlay-show + signal onto the mainloop thread (dbus-python
        # and the OverlayController's GLib work must run single-threaded there).
        from gi.repository import GLib

        GLib.idle_add(self._show_menu_and_signal)

    def _show_menu_and_signal(self) -> bool:
        """Raise the overlay and emit ``TriggerPressed`` (runs on the mainloop).

        Scheduled via ``GLib.idle_add`` from the HID reader thread so all
        OverlayController D-Bus / GLib-timeout work stays on the mainloop thread.
        Returns ``False`` so the idle source fires exactly once.
        """
        # Raise the radial overlay (lazily launching it if needed).
        self.show_menu()
        if self._dbus_service is not None:
            self._dbus_service.TriggerPressed()
        return False

    def show_menu(self, menu_id: Optional[str] = None) -> bool:
        """Raise the radial overlay for ``menu_id`` (async; never blocks).

        Shared by the Actions-Ring trigger path and the ``ShowMenu`` D-Bus
        method, so integration is testable without a physical panel tap. When
        ``menu_id`` is empty/None the configured ``[radial] default_menu`` is
        used. Returns whether the show request was dispatched.
        """
        if self._overlay is None:
            logger.warning("overlay controller unavailable; cannot show menu")
            return False
        return self._overlay.show_menu(menu_id)

    def _on_trigger_release(self, cid: int) -> None:
        """Handle an Actions-Ring release: emit D-Bus signal."""
        logger.debug("Actions Ring released (CID 0x%04X)", cid)
        if self._dbus_service is not None:
            self._dbus_service.TriggerReleased()

    # -- run -------------------------------------------------------------
    def run(self) -> int:
        """Set up everything and enter the GLib mainloop. Returns exit code."""
        self.setup()
        self._start_dbus()

        # Start the device-I/O worker before anything can enqueue to it.
        self._io_thread = threading.Thread(
            target=self._io_worker, name="mx4-io", daemon=True
        )
        self._io_thread.start()

        if self.trigger is not None:
            self.trigger.start()

        for src in self.sources:
            try:
                src.start(self.on_event)
            except Exception:  # noqa: BLE001 - a source must never kill the daemon
                logger.exception("source %s failed to start", src.kind)

        # Install signal handlers so we always restore the diverted control.
        from gi.repository import GLib

        self._mainloop = GLib.MainLoop()

        def _handle_signal() -> bool:
            logger.info("signal received; shutting down")
            self._mainloop.quit()
            return False

        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, _handle_signal)

        # Liveness watchdog: if the HID reader thread dies (device unplugged),
        # shut down cleanly instead of running on as a no-op zombie.
        def _watchdog() -> bool:
            transport = self.device.transport if self.device else None
            if transport is not None and not transport.reader_alive():
                self._note_device_lost()
                return False  # stop the timer; mainloop.quit() was requested
            return True  # keep polling

        GLib.timeout_add_seconds(2, _watchdog)

        logger.info(
            "mx4 daemon running (device=%s)", self.device.name if self.device else "?"
        )
        try:
            self._mainloop.run()
        finally:
            self.shutdown()
        return 0

    def _start_dbus(self) -> None:
        """Claim the session bus name and publish the daemon object."""
        try:
            import dbus
            import dbus.mainloop.glib
            import dbus.service

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            name = dbus.service.BusName(DBUS_BUS_NAME, bus)
            service_cls = _make_dbus_service_class()
            self._dbus_service = service_cls(self, bus, name)
            # Overlay control shares this connection (its async Show/Hide calls
            # and the bounded name-wait poll run on the same mainloop).
            self._overlay = OverlayController(
                bus,
                overlay_command=self.config.overlay_command,
                default_menu=self.config.radial_default_menu,
            )
            logger.info("D-Bus service published at %s", DBUS_BUS_NAME)
        except Exception:  # noqa: BLE001 - D-Bus is optional, daemon still useful
            logger.exception("failed to publish D-Bus service; continuing without it")
            self._dbus_service = None

    # -- shutdown --------------------------------------------------------
    def shutdown(self) -> None:
        """Restore the diverted control first, then stop sources and the device.

        The divert is restored *before* anything else so the user's mouse is
        left clean even if a later teardown step (e.g. the D-Bus monitor, a C
        extension) misbehaves. :meth:`TriggerWatcher.stop` is idempotent, so the
        atexit hook restoring it again is harmless.
        """
        if self._shutdown_done:
            return
        self._shutdown_done = True

        # 1. ALWAYS restore the panel to non-diverted, first and in isolation.
        if self.trigger is not None:
            try:
                self.trigger.stop()
            except Exception:  # noqa: BLE001
                logger.exception("error restoring diverted panel")

        # 2. Stop the device-I/O worker so nothing writes during teardown.
        if self._io_thread is not None:
            try:
                self._io_queue.put_nowait(_STOP)
            except queue.Full:
                # Drain one item to make room for the stop sentinel.
                try:
                    self._io_queue.get_nowait()
                    self._io_queue.put_nowait(_STOP)
                except queue.Empty:
                    pass
            self._io_thread.join(timeout=2.0)
            self._io_thread = None

        # 3a. Terminate a lazily-launched overlay (a user-started one is left).
        if self._overlay is not None:
            try:
                self._overlay.stop()
            except Exception:  # noqa: BLE001
                logger.debug("error stopping overlay", exc_info=True)

        # 3. Stop ambient sources (the dbus monitor teardown lives here).
        for src in self.sources:
            try:
                src.stop()
            except Exception:  # noqa: BLE001
                logger.debug("error stopping source %s", src.kind, exc_info=True)

        # 4. Close the HID transport last.
        if self.device is not None:
            try:
                self.device.close()
            except Exception:  # noqa: BLE001
                logger.debug("error closing device", exc_info=True)
        logger.info("mx4 daemon stopped")


def _make_dbus_service_class():
    """Construct the D-Bus service class lazily (needs dbus.service imported).

    Kept in a factory so importing :mod:`mx4d.daemon` never hard-requires dbus.
    """
    import dbus.service

    class Mx4DBusService(dbus.service.Object):
        """Session D-Bus object exposing PlayHaptic/SetLevel + trigger signals."""

        def __init__(self, daemon: "Mx4Daemon", bus, name):
            super().__init__(bus, DBUS_OBJECT_PATH, name)
            self._daemon = daemon

        @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="b")
        def PlayHaptic(self, waveform):  # noqa: N802 - D-Bus method name
            """Play a named/index waveform on demand (e.g. overlay tick).

            The blocking HID++ write is dispatched to the device-I/O worker so
            this D-Bus call never stalls the shared bus dispatch thread (the
            overlay hammers this on every hover tick). Returns whether the
            request was accepted/queued; the overlay treats it as
            fire-and-forget anyway.
            """
            if self._daemon.haptics is None:
                return False
            try:
                self._daemon._io_queue.put_nowait(("force_play", str(waveform)))
                return True
            except Exception:  # noqa: BLE001
                return False

        @dbus.service.method(DBUS_INTERFACE, in_signature="i", out_signature="b")
        def SetLevel(self, level):  # noqa: N802
            """Set the global haptic level (0..100).

            The actual blocking HID++ write is dispatched to the device-I/O
            worker so this D-Bus call never stalls on a slow/idle device (the
            shared bus dispatch must stay responsive). Returns whether the
            request was accepted/queued.
            """
            if self._daemon.haptics is None:
                return False
            try:
                self._daemon._io_queue.put_nowait(("set_level", int(level)))
                return True
            except Exception:  # noqa: BLE001
                return False

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="u")
        def GetCapabilities(self):  # noqa: N802 - D-Bus method name
            """Return the firmware's supported-waveform capability bitmask.

            Bit ``i`` set means waveform index ``i`` is supported (see
            ``haptics.WAVEFORMS``). The config GUI reads this to mark which
            waveforms the hardware actually plays; ``0`` means "unknown" (no
            device / capabilities not yet read), which the GUI treats as
            "show all, grey out none".
            """
            if self._daemon.haptics is None:
                return 0
            try:
                return int(self._daemon.haptics.capabilities) & 0xFFFFFFFF
            except Exception:  # noqa: BLE001
                return 0

        @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="b")
        def FocusChanged(self, app_name):  # noqa: N802 - D-Bus method name
            """Feed a native-Wayland focus change into the focus haptic mapping.

            A KWin script (packaging/kwin/) calls this on
            ``workspace.windowActivated`` so focus events surface even for pure
            Wayland clients that never touch X11 ``_NET_ACTIVE_WINDOW``. It runs
            the SAME per-source gating + haptic mapping as the X11 ``focus``
            source (master/quiet/per-source enable + debounce + waveform), so
            the two paths are interchangeable and the X11 baseline still works.

            Returns whether the event was dispatched (it is then gated like any
            ambient event; a debounced/disabled event still returns ``True``
            because it was accepted, just not played).
            """
            try:
                self._daemon.on_event(
                    Event(KIND_FOCUS, {"app": str(app_name), "source": "kwin"})
                )
                return True
            except Exception:  # noqa: BLE001 - never let a bad event kill the bus
                logger.debug("FocusChanged dispatch failed", exc_info=True)
                return False

        @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="b")
        def ShowMenu(self, menu_id):  # noqa: N802 - D-Bus method name
            """Raise the radial overlay for ``menu_id`` (programmatic trigger).

            Performs exactly what an Actions-Ring press does for the overlay
            (ensure the overlay is running, then ``Overlay.Show(menuId)``), so
            integration is testable without a physical panel tap. An empty
            ``menu_id`` uses the configured ``[radial] default_menu``. Returns
            whether the show request was dispatched. Non-blocking.
            """
            return bool(self._daemon.show_menu(str(menu_id)))

        @dbus.service.signal(DBUS_INTERFACE, signature="")
        def TriggerPressed(self):  # noqa: N802
            """Emitted when the Actions Ring panel is pressed."""

        @dbus.service.signal(DBUS_INTERFACE, signature="")
        def TriggerReleased(self):  # noqa: N802
            """Emitted when the Actions Ring panel is released."""

        @dbus.service.signal(DBUS_INTERFACE, signature="")
        def DeviceLost(self):  # noqa: N802
            """Emitted when the MX Master 4 disappears (unplugged/powered off)."""

    return Mx4DBusService
