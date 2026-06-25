"""OverlayController — drive the C++/Qt6 radial overlay over session D-Bus.

On an Actions-Ring trigger press (or the ``ShowMenu`` D-Bus method) the daemon
must raise the radial overlay. The overlay is a *separate* process that owns its
own well-known name ``dev.usidiamond.mx4.Overlay``; if it is not running yet we
**lazily launch** it (config ``[overlay] command``, default ``mx4-radial`` —
resolved on ``PATH``, or an absolute path for dev/testing), wait briefly for its
bus name to appear, then call ``Show(menuId)``.

Design constraints honoured here:

* **Never block the GLib mainloop.** ``show_menu`` returns immediately. When the
  overlay is already present we call ``Show`` straight away (async D-Bus call,
  no reply awaited). When it is absent we spawn the process and arm a *bounded*
  GLib timeout poll for the name to appear; each poll tick is a cheap, non-
  blocking ``NameHasOwner`` check. No sleeps, no synchronous round-trips.
* **Idempotent / no storms.** A launch already in flight is not relaunched; a
  second ``show_menu`` while we are waiting just replaces the pending menu id.
* **Graceful when D-Bus or the overlay binary is absent.** Every failure is
  logged and swallowed — the daemon keeps running and the panel stays usable.

D-Bus contract driven here (must match the overlay, do not change one side
only)::

    bus name : dev.usidiamond.mx4.Overlay
    object   : /dev/usidiamond/mx4/Overlay
    interface: dev.usidiamond.mx4.Overlay
    method   : Show(s menuId), Hide()
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Callable, Optional

logger = logging.getLogger(__name__)

OVERLAY_BUS_NAME = "dev.usidiamond.mx4.Overlay"
OVERLAY_OBJECT_PATH = "/dev/usidiamond/mx4/Overlay"
OVERLAY_INTERFACE = "dev.usidiamond.mx4.Overlay"

# How long to wait (total) for a freshly-launched overlay's bus name to appear,
# and how often to poll. Bounded so a launch that never registers gives up
# instead of polling forever. Qt app startup + bus registration is well under a
# second on a warm cache; 5 s is generous headroom without being annoying.
_WAIT_TOTAL_MS = 5000
_WAIT_POLL_MS = 100


class OverlayController:
    """Lazily launches and drives the radial overlay over session D-Bus.

    All public methods are safe to call from the daemon's HID reader thread or
    the GLib/dbus mainloop thread: they only ever *enqueue* async D-Bus work or
    arm GLib timeouts, never block.
    """

    def __init__(
        self,
        bus,
        *,
        overlay_command: str,
        default_menu: str = "default",
        on_dismissed=None,
    ) -> None:
        """:param bus: the daemon's already-connected ``dbus.SessionBus``.
        :param overlay_command: the command used to launch the overlay (bare
            name resolved on PATH, or an absolute path). From ``[overlay]
            command``.
        :param default_menu: menu id passed to ``Show`` when none is given.
        :param on_dismissed: optional 0-arg callback invoked (on the GLib
            mainloop) when the overlay emits ``Dismissed`` — i.e. it closed for
            any reason (committed action, cancel, or an external ``Hide``). The
            daemon uses it to track visibility for press-again-to-dismiss.
        """
        self._bus = bus
        self._overlay_command = overlay_command
        self._default_menu = default_menu or "default"
        self._on_dismissed = on_dismissed

        # Listen for the overlay's Dismissed signal regardless of whether the
        # overlay is running yet (subscription is by interface+path, so it
        # survives the overlay being lazily (re)launched). Best-effort: a bus
        # without signal support just means we never auto-clear visibility.
        if bus is not None and on_dismissed is not None:
            try:
                bus.add_signal_receiver(
                    self._handle_dismissed,
                    signal_name="Dismissed",
                    dbus_interface=OVERLAY_INTERFACE,
                    path=OVERLAY_OBJECT_PATH,
                )
            except Exception:  # noqa: BLE001 - signal wiring is best-effort
                logger.debug("could not subscribe to overlay Dismissed", exc_info=True)

        # The action to run once the overlay's name is available (a 0-arg
        # callable: Show(menu) or ShowMedia). Set while a launch/wait is in
        # flight; consumed (cleared) when it fires.
        self._pending: Optional[Callable[[], None]] = None
        # True between spawning the process and either calling Show or timing
        # out — prevents a second launch while one is already starting.
        self._launching = False
        self._proc = None  # the subprocess.Popen we lazily started, if any.
        # GLib source id of the in-flight name-wait poll, so stop() can disarm a
        # pending wait at shutdown instead of letting it fire on a torn-down bus.
        self._wait_source = 0

    # -- public API ------------------------------------------------------
    def show_menu(self, menu_id: Optional[str] = None) -> bool:
        """Ensure the overlay is up and show ``menu_id`` (async; never blocks).

        Returns ``True`` if the request was dispatched/queued (the overlay was
        present and we called Show, or we launched it and armed the wait),
        ``False`` only if we could not even attempt it (no bus). The actual
        Show is fire-and-forget — a ``True`` does not guarantee the ring drew,
        only that the daemon did its part without stalling.
        """
        menu = menu_id if menu_id else self._default_menu
        if self._bus is None:
            logger.warning("no session bus; cannot show overlay")
            return False

        if self._overlay_running():
            # Fast path: overlay already resident, just call Show.
            self._call_show(menu)
            return True

        # Overlay absent. Remember what to show and (re)launch + wait for it.
        self._pending = lambda: self._call_show(menu)
        if self._launching:
            logger.debug("overlay launch already in flight; updated pending action")
            return True
        return self._launch_and_wait()

    def show_media(self) -> bool:
        """Ensure the overlay is up and show the MPRIS media panel (async).

        Mirrors :meth:`show_menu` but raises the media-controls panel instead of
        a radial ring. Never blocks; returns whether the request was dispatched
        or queued behind a lazy launch.
        """
        if self._bus is None:
            logger.warning("no session bus; cannot show media panel")
            return False
        if self._overlay_running():
            self._call_show_media()
            return True
        self._pending = self._call_show_media
        if self._launching:
            logger.debug("overlay launch already in flight; updated pending action")
            return True
        return self._launch_and_wait()

    def hide(self) -> None:
        """Ask the overlay to hide (no-op if it is not running)."""
        if self._bus is None or not self._overlay_running():
            return
        try:
            obj = self._bus.get_object(OVERLAY_BUS_NAME, OVERLAY_OBJECT_PATH)
            iface = self._proxy_iface(obj)
            iface.Hide(ignore_reply=True)
        except Exception:  # noqa: BLE001 - overlay control is best-effort
            logger.debug("overlay Hide() failed", exc_info=True)

    def _handle_dismissed(self, *_args) -> None:
        """D-Bus ``Dismissed`` signal handler: the overlay just closed."""
        if self._on_dismissed is None:
            return
        try:
            self._on_dismissed()
        except Exception:  # noqa: BLE001 - never let a callback kill the bus loop
            logger.debug("on_dismissed callback raised", exc_info=True)

    def stop(self) -> None:
        """Terminate an overlay process *we* launched (leave a user-started one).

        Called on daemon shutdown so a lazily-spawned overlay does not outlive
        the daemon. A overlay the user started independently is left alone.
        """
        # Disarm an in-flight name-wait poll so it cannot call Show on a
        # torn-down bus during shutdown, and short-circuit any pending wait.
        if self._wait_source:
            try:
                from gi.repository import GLib

                GLib.source_remove(self._wait_source)
            except Exception:  # noqa: BLE001
                pass
            self._wait_source = 0
        self._launching = False
        self._pending = None

        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is not None:
            return  # already exited
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # -- internals -------------------------------------------------------
    def _overlay_running(self) -> bool:
        """Cheap, non-blocking check: does anyone own the overlay bus name?"""
        try:
            return bool(self._bus.name_has_owner(OVERLAY_BUS_NAME))
        except Exception:  # noqa: BLE001
            logger.debug("name_has_owner check failed", exc_info=True)
            return False

    def _resolve_command(self) -> Optional[list[str]]:
        """Resolve the configured overlay command to an argv list, or None.

        Accepts a bare binary name (resolved on ``PATH``) or an absolute path.
        Returns ``None`` (logged) when the binary cannot be found so we never
        hand an unresolvable command to the spawner.
        """
        cmd = self._overlay_command.strip()
        if not cmd:
            return None
        # Absolute (or explicitly relative) path: use as-is if it exists.
        if cmd.startswith(("/", "./", "../")):
            return [cmd]
        resolved = shutil.which(cmd)
        if resolved is None:
            logger.error(
                "overlay command %r not found on PATH; cannot launch overlay", cmd
            )
            return None
        return [resolved]

    def _launch_and_wait(self) -> bool:
        """Spawn the overlay and arm a bounded GLib poll for its bus name.

        Never blocks: the wait is a repeating GLib timeout that, on each tick,
        does a cheap ``name_has_owner`` check and calls Show + disarms once the
        name appears (or gives up after the bound).
        """
        argv = self._resolve_command()
        if argv is None:
            self._pending = None
            return False

        import subprocess

        try:
            # No shell (argv list) so menu/command config cannot inject. The
            # overlay runs in SERVICE mode (no --demo) so it stays resident.
            self._proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
                argv,
                stdin=subprocess.DEVNULL,
            )
            logger.info("launched overlay: %s (pid %d)", " ".join(argv), self._proc.pid)
        except OSError as exc:
            logger.error("failed to launch overlay %s: %s", argv, exc)
            self._pending = None
            return False

        self._launching = True
        self._arm_wait()
        return True

    def _arm_wait(self) -> None:
        """Arm the bounded GLib timeout that polls for the overlay's name."""
        from gi.repository import GLib

        elapsed = {"ms": 0}

        def _poll() -> bool:
            # Overlay process died before registering — give up.
            if self._proc is not None and self._proc.poll() is not None:
                logger.error("overlay process exited before registering its bus name")
                self._launching = False
                self._pending = None
                self._wait_source = 0
                return False  # stop the timer

            if self._overlay_running():
                pending = self._pending
                self._pending = None
                self._launching = False
                self._wait_source = 0
                # Run the queued action (Show(menu) or ShowMedia); default to the
                # default menu if somehow nothing was queued.
                (pending or (lambda: self._call_show(self._default_menu)))()
                return False  # stop the timer

            elapsed["ms"] += _WAIT_POLL_MS
            if elapsed["ms"] >= _WAIT_TOTAL_MS:
                logger.error(
                    "overlay bus name %s did not appear within %d ms; giving up",
                    OVERLAY_BUS_NAME,
                    _WAIT_TOTAL_MS,
                )
                self._launching = False
                self._pending = None
                self._wait_source = 0
                return False  # stop the timer
            return True  # keep polling

        self._wait_source = GLib.timeout_add(_WAIT_POLL_MS, _poll)

    def _call_show(self, menu_id: str) -> None:
        """Call ``Overlay.Show(menu_id)`` async (fire-and-forget, never blocks)."""
        try:
            obj = self._bus.get_object(OVERLAY_BUS_NAME, OVERLAY_OBJECT_PATH)
            iface = self._proxy_iface(obj)
            # ignore_reply=True => async, the mainloop is never blocked on the
            # overlay drawing its surface.
            iface.Show(menu_id, ignore_reply=True)
            logger.info("overlay Show(%s) dispatched", menu_id)
        except Exception:  # noqa: BLE001 - overlay control is best-effort
            logger.exception("overlay Show(%s) failed", menu_id)

    def _call_show_media(self) -> None:
        """Call ``Overlay.ShowMedia()`` async (fire-and-forget, never blocks)."""
        try:
            obj = self._bus.get_object(OVERLAY_BUS_NAME, OVERLAY_OBJECT_PATH)
            iface = self._proxy_iface(obj)
            iface.ShowMedia(ignore_reply=True)
            logger.info("overlay ShowMedia() dispatched")
        except Exception:  # noqa: BLE001 - overlay control is best-effort
            logger.exception("overlay ShowMedia() failed")

    @staticmethod
    def _proxy_iface(obj):
        """Return the overlay interface proxy for a D-Bus object."""
        import dbus

        return dbus.Interface(obj, OVERLAY_INTERFACE)
