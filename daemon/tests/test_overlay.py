"""Unit tests for the OverlayController command resolution + show fast-path.

These exercise the pure logic (command resolution, the already-running fast
path, hide no-op) against a fake D-Bus bus, with no real session bus, no GLib
mainloop and no overlay process — so they run anywhere the daemon package
imports.
"""

from __future__ import annotations

from mx4d import overlay as overlaymod
from mx4d.overlay import OverlayController


class FakeIface:
    """Records Show/Hide calls instead of talking to a real overlay."""

    def __init__(self):
        self.shows = []
        self.hides = 0

    def Show(self, menu_id, ignore_reply=False):  # noqa: N802 - mirrors D-Bus name
        self.shows.append(menu_id)

    def Hide(self, ignore_reply=False):  # noqa: N802
        self.hides += 1


class FakeBus:
    """Minimal stand-in for dbus.SessionBus for the controller's needs."""

    def __init__(self, *, owner: bool):
        self._owner = owner

    def name_has_owner(self, name):  # noqa: D401 - mirrors dbus API
        return self._owner

    def get_object(self, bus_name, object_path):
        return object()  # the controller's _proxy_iface is monkeypatched


def _controller(bus, iface, monkeypatch, **kwargs):
    c = OverlayController(bus, overlay_command="mx4-radial", **kwargs)
    monkeypatch.setattr(c, "_proxy_iface", staticmethod(lambda obj: iface))
    return c


def test_resolve_absolute_path_used_verbatim():
    c = OverlayController(object(), overlay_command="/home/me/build/mx4-radial")
    assert c._resolve_command() == ["/home/me/build/mx4-radial"]


def test_resolve_bare_name_uses_path(monkeypatch):
    monkeypatch.setattr(
        overlaymod.shutil, "which",
        lambda name: "/usr/bin/mx4-radial" if name == "mx4-radial" else None,
    )
    c = OverlayController(object(), overlay_command="mx4-radial")
    assert c._resolve_command() == ["/usr/bin/mx4-radial"]


def test_resolve_missing_bare_name_returns_none(monkeypatch):
    monkeypatch.setattr(overlaymod.shutil, "which", lambda name: None)
    c = OverlayController(object(), overlay_command="does-not-exist")
    assert c._resolve_command() is None


def test_show_fast_path_calls_show_when_overlay_running(monkeypatch):
    iface = FakeIface()
    bus = FakeBus(owner=True)
    c = _controller(bus, iface, monkeypatch)
    assert c.show_menu("work") is True
    assert iface.shows == ["work"]


def test_show_uses_default_menu_when_none(monkeypatch):
    iface = FakeIface()
    bus = FakeBus(owner=True)
    c = _controller(bus, iface, monkeypatch, default_menu="ambient")
    assert c.show_menu(None) is True
    assert iface.shows == ["ambient"]


def test_show_returns_false_without_bus():
    c = OverlayController(None, overlay_command="mx4-radial")
    assert c.show_menu("default") is False


def test_hide_is_noop_when_overlay_absent(monkeypatch):
    iface = FakeIface()
    bus = FakeBus(owner=False)
    c = _controller(bus, iface, monkeypatch)
    c.hide()  # overlay not running -> never touches the iface
    assert iface.hides == 0


def test_hide_calls_overlay_when_running(monkeypatch):
    iface = FakeIface()
    bus = FakeBus(owner=True)
    c = _controller(bus, iface, monkeypatch)
    c.hide()
    assert iface.hides == 1


def test_stop_without_launched_process_is_safe():
    c = OverlayController(object(), overlay_command="mx4-radial")
    c.stop()  # no process was launched -> no-op, must not raise
