"""HapticEngine — fire the MX Master 4's haptic motor (feature ``0x19B0``).

Wraps the haptic feature with:

* runtime capability gating (function ``0x00`` returns a supported-waveform
  bitmask; we refuse to play an unsupported waveform),
* level get/set (function ``0x10`` / ``0x20``, 0..100),
* the proven fire-and-forget "play" packet (function ``0x40``),
* debounce / rate-limiting so a burst of ambient events does not machine-gun
  the motor.

The on-wire play packet (proven on real hardware) for waveform ``w`` on device
``d`` at haptic feature index ``F`` is::

    bytes([0x10, d, F, 0x4E, w, 0x00, 0x00])

where ``0x4E`` is ``(0x4 << 4) | 0x0E`` — the play function (``0x40``) already
shifted, OR'd with software id ``0x0E``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Union

from .hidpp import SHORT_REPORT_ID, HidppTransport, func_byte

logger = logging.getLogger(__name__)

# Haptic feature (0x19B0) function ids (the function nibble).
HAPTIC_FN_GET_CAPABILITIES = 0x0
HAPTIC_FN_GET_LEVEL = 0x1
HAPTIC_FN_SET_LEVEL = 0x2
HAPTIC_FN_PLAY = 0x4

# The fully-encoded function byte for "play" — (0x4 << 4) | 0x0E.
PLAY_FUNC_BYTE = func_byte(HAPTIC_FN_PLAY)  # == 0x4E

# Waveform name -> index. Sparse on purpose (gated by the capability bitmask).
WAVEFORMS: dict[str, int] = {
    "SHARP_STATE_CHANGE": 0x00,
    "DAMP_STATE_CHANGE": 0x01,
    "SHARP_COLLISION": 0x02,
    "DAMP_COLLISION": 0x03,
    "SUBTLE_COLLISION": 0x04,
    "HAPPY_ALERT": 0x05,
    "ANGRY_ALERT": 0x06,
    "COMPLETED": 0x07,
    "SQUARE": 0x08,
    "WAVE": 0x09,
    "FIREWORK": 0x0A,
    "MAD": 0x0B,
    "KNOCK": 0x0C,
    "JINGLE": 0x0D,
    "RINGING": 0x0E,
    "WHISPER_COLLISION": 0x1B,
}

# Reverse lookup for logging.
WAVEFORM_NAMES = {v: k for k, v in WAVEFORMS.items()}

# Ordered preference list used when a requested waveform is unsupported by the
# device firmware (the MX4 we tested only exposes a subset — capability mask
# 0x0001003C => SHARP/DAMP/SUBTLE_COLLISION, HAPPY_ALERT, and 0x10). We fall
# back to the closest supported waveform so an event still produces a tick.
FALLBACK_ORDER = [
    0x05,  # HAPPY_ALERT
    0x04,  # SUBTLE_COLLISION
    0x03,  # DAMP_COLLISION
    0x02,  # SHARP_COLLISION
]


def resolve_waveform(token: Union[str, int]) -> int:
    """Resolve a waveform name or numeric token to its index.

    Accepts a known name (case-insensitive, spaces -> underscores), an int, or
    a numeric string like ``"0x07"``.
    """
    if isinstance(token, int):
        return token & 0xFF
    key = token.strip().upper().replace(" ", "_")
    if key in WAVEFORMS:
        return WAVEFORMS[key]
    return int(key, 0) & 0xFF


class HapticEngine:
    """Plays haptic waveforms on one MX Master 4, with gating and debounce."""

    def __init__(
        self,
        transport: HidppTransport,
        haptic_index: int,
        *,
        min_interval: float = 0.12,
        preset_capabilities: Optional[int] = None,
    ) -> None:
        """Bind to a device's haptic feature.

        :param transport: an open :class:`~mx4d.hidpp.HidppTransport`.
        :param haptic_index: runtime feature index of ``0x19B0``.
        :param min_interval: minimum seconds between plays (debounce). Plays
            arriving sooner are coalesced (dropped), so bursts feel like one tick.
        """
        self.transport = transport
        self.haptic_index = haptic_index
        self.min_interval = min_interval
        # When preset (Solaar coexist), the capability mask is supplied without a
        # request/response read (which would contend with a running Solaar), so
        # play() can gate without ever doing a blocking HID++ round-trip.
        self._capabilities: Optional[int] = preset_capabilities
        self._last_play = 0.0
        self._lock = threading.Lock()

    # -- capabilities ----------------------------------------------------
    def read_capabilities(self) -> int:
        """Read and cache the supported-waveform bitmask (function ``0x00``).

        The bitmask occupies reply bytes 4..7 (little contiguous run); bit ``i``
        set means waveform index ``i`` is supported.
        """
        reply = self.transport.call(self.haptic_index, HAPTIC_FN_GET_CAPABILITIES)
        mask = int.from_bytes(reply[4:8], "big")
        self._capabilities = mask
        logger.debug("haptic capability bitmask = 0x%08X", mask)
        return mask

    @property
    def capabilities(self) -> int:
        """The cached capability bitmask, reading it lazily on first access."""
        if self._capabilities is None:
            self.read_capabilities()
        return self._capabilities or 0

    def supports(self, waveform: Union[str, int]) -> bool:
        """Return whether ``waveform`` is supported per the capability bitmask."""
        index = resolve_waveform(waveform)
        return bool((1 << index) & self.capabilities)

    # -- level -----------------------------------------------------------
    def get_level(self) -> int:
        """Return the current haptic level (0..100) via function ``0x10``."""
        reply = self.transport.call(self.haptic_index, HAPTIC_FN_GET_LEVEL)
        return reply[5]

    def is_enabled(self) -> bool:
        """Return whether haptics are enabled on the device (function ``0x10``)."""
        reply = self.transport.call(self.haptic_index, HAPTIC_FN_GET_LEVEL)
        return bool(reply[4] & 0x01)

    def set_level(self, level: int) -> None:
        """Set the haptic level (0..100) and enable haptics (function ``0x20``).

        Params are ``b"\\x01" + level`` per the reverse-engineered protocol.
        """
        level = max(0, min(100, int(level)))
        self.transport.call(self.haptic_index, HAPTIC_FN_SET_LEVEL, 0x01, level)
        logger.debug("set haptic level to %d", level)

    def disable(self) -> None:
        """Disable haptics on the device (function ``0x20`` with ``00 32``)."""
        self.transport.call(self.haptic_index, HAPTIC_FN_SET_LEVEL, 0x00, 0x32)

    # -- debounce --------------------------------------------------------
    def should_play(self) -> bool:
        """Atomically check + claim the debounce window for an ambient event.

        Returns ``True`` and resets the debounce clock if at least
        ``min_interval`` seconds have elapsed since the last play; returns
        ``False`` otherwise. Callers use this to drop a coalesced burst BEFORE
        doing any device I/O (so a storm never issues a HID round-trip per
        event). A subsequent ``play(..., force=True)`` then performs the write.
        """
        with self._lock:
            now = time.monotonic()
            if (now - self._last_play) < self.min_interval:
                return False
            self._last_play = now
            return True

    # -- play ------------------------------------------------------------
    def build_play_packet(self, waveform: Union[str, int]) -> bytes:
        """Return the exact on-wire play packet for ``waveform``.

        Exposed so unit tests can assert the byte-for-byte contract.
        """
        index = resolve_waveform(waveform)
        return bytes(
            [
                SHORT_REPORT_ID,
                self.transport.device_index,
                self.haptic_index,
                PLAY_FUNC_BYTE,
                index & 0xFF,
                0x00,
                0x00,
            ]
        )

    def _best_supported(self, index: int) -> Optional[int]:
        """Return ``index`` if supported, else a supported fallback, else None."""
        if self.supports(index):
            return index
        for candidate in FALLBACK_ORDER:
            if self.supports(candidate):
                return candidate
        return None

    def play(
        self, waveform: Union[str, int], *, force: bool = False, fallback: bool = True
    ) -> bool:
        """Play a waveform, honoring capability gating and debounce.

        :param waveform: a name (e.g. ``"COMPLETED"``) or index.
        :param force: bypass the debounce interval (e.g. for the trigger tick).
        :param fallback: if the requested waveform is unsupported, substitute the
            closest supported one (per :data:`FALLBACK_ORDER`) rather than going
            silent. Set ``False`` for strict capability checks (e.g. selftest).
        :returns: ``True`` if a packet was written, ``False`` if gated/debounced.
        """
        requested = resolve_waveform(waveform)
        name = WAVEFORM_NAMES.get(requested, "0x%02X" % requested)

        if self.supports(requested):
            index = requested
        elif fallback:
            substitute = self._best_supported(requested)
            if substitute is None:
                logger.warning("no supported waveform available; skipping %s", name)
                return False
            sub_name = WAVEFORM_NAMES.get(substitute, "0x%02X" % substitute)
            logger.info("waveform %s unsupported; falling back to %s", name, sub_name)
            index = substitute
            name = sub_name
        else:
            logger.warning("waveform %s not supported by device; skipping", name)
            return False

        with self._lock:
            now = time.monotonic()
            if not force and (now - self._last_play) < self.min_interval:
                logger.debug("debounced waveform %s", name)
                return False
            self._last_play = now

        packet = self.build_play_packet(index)
        try:
            self.transport.write_raw(packet)
        except OSError as exc:
            logger.error("failed to write haptic packet: %s", exc)
            return False
        logger.info("played haptic %s", name)
        return True
