"""System-sound source (best-effort, PipeWire / PulseAudio).

Stretch goal. If ``pactl`` (or ``pw-mon``) is present we subscribe to the audio
server and emit a sound event when a new short-lived playback stream appears
(the event-sound pattern). If neither tool exists, the source disables itself
cleanly — it never hard-fails.

Notes / honesty:
* Many desktop "sounds" are the audible side of a notification and are already
  covered by :mod:`mx4d.sources.notifications`; this source is scaffolding plus
  a config toggle, off by default, so users who want a buzz on *any* new audio
  stream can opt in.
* ``pactl subscribe`` reports sink-input add/remove; we treat an *add* of a
  sink-input as a sound event. This is coarse (music playback also triggers it),
  hence the source defaults to disabled in config.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

from . import KIND_SOUND, EmitCallback, Event, Source

logger = logging.getLogger(__name__)


class SoundsSource(Source):
    """Emit a sound event when a new playback stream appears (pactl/pw-mon)."""

    kind = KIND_SOUND

    def __init__(self) -> None:
        self._emit: Optional[EmitCallback] = None
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._tool: Optional[str] = None

    def available(self) -> bool:
        """Available only if ``pactl`` or ``pw-mon`` is on PATH."""
        return shutil.which("pactl") is not None or shutil.which("pw-mon") is not None

    def start(self, emit: EmitCallback) -> bool:
        """Subscribe to the audio server; disable gracefully if unavailable."""
        self._emit = emit
        pactl = shutil.which("pactl")
        if pactl is not None:
            return self._start_pactl(pactl)
        pwmon = shutil.which("pw-mon")
        if pwmon is not None:
            return self._start_pwmon(pwmon)
        logger.info("sounds source: no pactl/pw-mon; disabled")
        return False

    def _start_pactl(self, pactl: str) -> bool:
        """Run ``pactl subscribe`` and watch for sink-input additions."""
        try:
            self._proc = subprocess.Popen(
                [pactl, "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            logger.info("sounds source: pactl failed (%s); disabled", exc)
            return False
        self._tool = "pactl"
        return self._spawn_reader(self._read_pactl)

    def _start_pwmon(self, pwmon: str) -> bool:
        """Run ``pw-mon`` (coarser; just logs additions of nodes)."""
        try:
            self._proc = subprocess.Popen(
                [pwmon],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            logger.info("sounds source: pw-mon failed (%s); disabled", exc)
            return False
        self._tool = "pw-mon"
        return self._spawn_reader(self._read_pwmon)

    def _spawn_reader(self, target) -> bool:
        self._stop.clear()
        self._thread = threading.Thread(
            target=target, name="sounds-reader", daemon=True
        )
        self._thread.start()
        logger.info("sounds source: subscribed via %s", self._tool)
        return True

    def _read_pactl(self) -> None:
        """Emit on lines like ``Event 'new' on sink-input #NN``."""
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            if "'new'" in line and "sink-input" in line:
                self._do_emit()

    def _read_pwmon(self) -> None:
        """Emit on a newly added Stream/Output node (best effort, coarse)."""
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            if line.lstrip().startswith("added:") and "Node" in line:
                self._do_emit()

    def _do_emit(self) -> None:
        if self._emit is not None:
            self._emit(Event(KIND_SOUND, {"tool": self._tool}))

    def stop(self) -> None:
        """Stop the subscription. Idempotent."""
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
