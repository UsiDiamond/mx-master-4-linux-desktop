"""State-machine tests for the daemon's tap / hold / flick / seek-scrub gesture.

These exercise :class:`mx4d.daemon.Mx4Daemon`'s trigger handlers directly with a
recording fake overlay. The handlers marshal overlay work onto the GLib mainloop
via ``GLib.idle_add``; we patch that to run inline so a synchronous test can
assert on the resulting overlay calls without spinning a real mainloop.
"""

from __future__ import annotations

import time

import pytest

from mx4d.config import default_config
from mx4d.daemon import Mx4Daemon


class FakeOverlay:
    """Records the OverlayController calls the daemon makes."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def show_menu(self, menu=None) -> bool:
        self.calls.append(("show_menu", menu))
        return True

    def show_media(self) -> bool:
        self.calls.append(("show_media",))
        return True

    def show_flick_ring(self, menu=None) -> bool:
        self.calls.append(("show_flick_ring", menu))
        return True

    def set_flick_vector(self, dx, dy) -> None:
        self.calls.append(("set_flick_vector", dx, dy))

    def commit_flick(self) -> None:
        self.calls.append(("commit_flick",))

    def scrub_seek(self, dx) -> None:
        self.calls.append(("scrub_seek", dx))

    def commit_seek(self) -> None:
        self.calls.append(("commit_seek",))

    def hide(self) -> None:
        self.calls.append(("hide",))

    # convenience for assertions
    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def daemon(monkeypatch):
    """A daemon wired to a fake overlay, with idle_add running inline."""
    from gi.repository import GLib

    monkeypatch.setattr(GLib, "idle_add", lambda fn, *a: (fn(*a), 0)[1])

    cfg = default_config()  # flick=True, flick_start=260
    d = Mx4Daemon(config=cfg)
    d.haptics = None  # _buzz_trigger becomes a no-op
    overlay = FakeOverlay()
    d._overlay = overlay
    return d, overlay


CID = 0x01A0


def _drop_then(d, dx, dy):
    """First raw-XY sample of a press is the bogus one we drop; then a real one."""
    d._on_trigger_raw_xy(99999, 99999)  # bogus first report -> dropped
    d._on_trigger_raw_xy(dx, dy)


def test_quick_tap_opens_ring(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    d._on_trigger_tap(CID)  # released within the hold window
    d._on_trigger_release(CID)
    assert overlay.names() == ["show_menu"]
    assert d._press_mode == "idle"


def test_hold_opens_media_then_release_without_slide(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    d._on_trigger_hold(CID)  # hold timer fired -> media
    d._on_trigger_release(CID)
    assert overlay.names() == ["show_media"]  # no commit_seek (no slide)


def test_slide_while_pressed_promotes_to_flick(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    # Cross the start threshold (260): net (200,200) -> mag^2 80000 >= 67600.
    _drop_then(d, 200, 200)
    assert d._press_mode == "flick"
    # A further sample streams the vector to the ring (throttle is open at t0).
    d._on_trigger_raw_xy(40, -10)
    # A quick release after a flick must COMMIT, not tap.
    d._on_trigger_tap(CID)  # suppressed
    d._on_trigger_release(CID)
    names = overlay.names()
    assert names[0] == "show_flick_ring"
    assert "set_flick_vector" in names
    assert names[-1] == "commit_flick"
    assert "show_menu" not in names  # tap was suppressed
    assert d._press_mode == "idle"


def test_small_wobble_stays_a_tap(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    # A tiny incidental move (well under flick_start=260) must NOT promote.
    _drop_then(d, 30, 20)
    assert d._press_mode == "pending"
    d._on_trigger_tap(CID)
    d._on_trigger_release(CID)
    assert overlay.names() == ["show_menu"]


def test_slide_in_media_mode_scrubs_and_commits(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    d._on_trigger_hold(CID)  # -> media, mode MEDIA
    assert d._press_mode == "media"
    _drop_then(d, 300, 0)  # horizontal slide -> scrub
    d._on_trigger_release(CID)
    names = overlay.names()
    assert names[0] == "show_media"
    assert ("scrub_seek", 300) in overlay.calls
    assert names[-1] == "commit_seek"


def test_flick_disabled_keeps_pure_tap_hold(daemon):
    d, overlay = daemon
    d.config.trigger_flick = False
    d._on_trigger_press(CID)
    _drop_then(d, 5000, 5000)  # huge slide, but flick is off
    assert d._press_mode == "pending"  # never promoted
    d._on_trigger_tap(CID)
    d._on_trigger_release(CID)
    assert overlay.names() == ["show_menu"]  # behaves exactly like a tap


def test_vector_send_is_throttled(daemon):
    d, overlay = daemon
    d._on_trigger_press(CID)
    _drop_then(d, 300, 0)  # -> flick + begin
    # Two immediate samples: the throttle should collapse them to one send.
    d._on_trigger_raw_xy(10, 0)
    d._on_trigger_raw_xy(10, 0)
    sends_now = overlay.names().count("set_flick_vector")
    # Wait past the throttle window and send again -> one more.
    time.sleep(_throttle_gap())
    d._on_trigger_raw_xy(10, 0)
    sends_after = overlay.names().count("set_flick_vector")
    assert sends_after == sends_now + 1


def _throttle_gap() -> float:
    from mx4d.daemon import _VECTOR_SEND_INTERVAL

    return _VECTOR_SEND_INTERVAL + 0.005
