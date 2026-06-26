"""Ambient event sources.

Each source is a small object with :meth:`Source.start` (given an ``emit``
callback) and :meth:`Source.stop`. A source produces :class:`Event` objects the
daemon maps to haptic waveforms. Sources degrade gracefully: a missing
dependency disables that one source (logged) rather than crashing the daemon.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# kind constants used across the daemon + config (matches config source keys).
KIND_NOTIFICATION = "notification"
KIND_FOCUS = "focus"
KIND_SOUND = "sound"


@dataclass
class Event:
    """An ambient event emitted by a source.

    :param kind: one of the ``KIND_*`` constants.
    :param meta: free-form details (e.g. ``{"urgency": 2, "app": "foo"}``).
    """

    kind: str
    meta: dict[str, Any] = field(default_factory=dict)


EmitCallback = Callable[[Event], None]


class Source:
    """Base class for an ambient event source.

    Subclasses set :attr:`kind` and implement :meth:`start` / :meth:`stop`.
    :meth:`available` lets the daemon skip a source whose dependencies are
    absent without ever raising.
    """

    kind: str = "base"

    def available(self) -> bool:
        """Return whether this source can run on this system."""
        return True

    def start(self, emit: EmitCallback) -> bool:
        """Begin producing events via ``emit``. Return success (never raise)."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop producing events and release resources. Idempotent."""
        raise NotImplementedError
