"""Application-focus source (X11 ``_NET_ACTIVE_WINDOW``).

Watches the root window's ``_NET_ACTIVE_WINDOW`` property via ``PropertyNotify``
and emits a focus event whenever the active window changes. This is the correct
portable path on X11 and is fully native on LXQt; on KDE Plasma it covers the
Xwayland session (``DISPLAY=:1`` here).

Honest limitation: native-Wayland-only clients may not surface a change in
``_NET_ACTIVE_WINDOW`` because they are not X11 windows. A KWin-script bridge to
the daemon's D-Bus interface is the planned Wayland-native complement; this
source is the portable X11 baseline.

It runs its own daemon thread with a dedicated Xlib display connection so it
never blocks the GLib mainloop.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from . import KIND_FOCUS, EmitCallback, Event, Source

logger = logging.getLogger(__name__)


class FocusSource(Source):
    """Emit a focus event on each ``_NET_ACTIVE_WINDOW`` change."""

    kind = KIND_FOCUS

    def __init__(self) -> None:
        self._emit: Optional[EmitCallback] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._display = None
        self._last_active: Optional[int] = None

    def available(self) -> bool:
        """Available if python-Xlib imports and an X display can be opened."""
        try:
            from Xlib import display  # noqa: F401
        except ImportError:
            return False
        try:
            from Xlib import display

            d = display.Display()
            d.close()
            return True
        except Exception:  # noqa: BLE001 - no X server / bad DISPLAY
            return False

    def start(self, emit: EmitCallback) -> bool:
        """Open the display, select PropertyChange on root, run the loop."""
        self._emit = emit
        try:
            from Xlib import X, display
        except ImportError:
            logger.warning("focus source: python-Xlib missing; disabled")
            return False
        try:
            self._display = display.Display()
        except Exception as exc:  # noqa: BLE001
            logger.warning("focus source: cannot open X display (%s); disabled", exc)
            return False

        root = self._display.screen().root
        root.change_attributes(event_mask=X.PropertyChangeMask)
        self._atom = self._display.intern_atom("_NET_ACTIVE_WINDOW")
        self._root = root
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="focus-xlib", daemon=True
        )
        self._thread.start()
        logger.info("focus source: watching _NET_ACTIVE_WINDOW")
        return True

    def _run(self) -> None:
        """Block on X events, emitting on _NET_ACTIVE_WINDOW PropertyNotify."""
        from Xlib import X, error

        assert self._display is not None
        while not self._stop.is_set():
            try:
                # pending_events()+next_event() lets us poll the stop flag.
                if self._display.pending_events() == 0:
                    # Short blocking wait via a fileno select would be ideal;
                    # Xlib has no timeout, so we use a tiny sleep-free poll loop
                    # gated on the connection's fd.
                    import select

                    readable, _, _ = select.select(
                        [self._display.fileno()], [], [], 0.5
                    )
                    if not readable:
                        continue
                event = self._display.next_event()
            except (error.ConnectionClosedError, OSError):
                break
            except Exception:  # noqa: BLE001
                logger.debug("focus source: X event error", exc_info=True)
                continue
            if event.type != X.PropertyNotify:
                continue
            if event.atom != self._atom:
                continue
            self._handle_active_change()

    def _handle_active_change(self) -> None:
        """Read the new active window id and emit if it actually changed."""
        try:
            prop = self._root.get_full_property(self._atom, 0)
        except Exception:  # noqa: BLE001
            return
        if prop is None or not prop.value:
            return
        active = int(prop.value[0])
        if active == self._last_active:
            return
        self._last_active = active
        if self._emit is not None:
            self._emit(Event(KIND_FOCUS, {"window": active}))

    def stop(self) -> None:
        """Stop the loop and close the display. Idempotent."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._display is not None:
            try:
                self._display.close()
            except Exception:  # noqa: BLE001
                pass
            self._display = None
