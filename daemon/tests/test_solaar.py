"""Unit tests for Solaar detection + the auto divert decision.

The detector is pure process-list inspection (no hardware, no real Solaar), so we
drive it by mocking ``mx4d.solaar._iter_proc_cmdlines`` with a synthetic process
table. The auto decision is exercised by mocking ``solaar_running`` and resolving
the daemon's effective divert without touching a device (we call
``Mx4Daemon._resolve_divert`` directly with a fake config).
"""

from __future__ import annotations

from mx4d import solaar as solaarmod
from mx4d.config import (
    DIVERT_AUTO,
    DIVERT_FALSE,
    DIVERT_TRUE,
    default_config,
)
from mx4d.daemon import Mx4Daemon
from mx4d.solaar import _is_solaar_background_cmdline, solaar_running

# -- cmdline classification --------------------------------------------------


def test_background_solaar_matches():
    # The real live process on this box: python launching the solaar program.
    assert _is_solaar_background_cmdline(
        ["/usr/bin/python3.14", "/usr/lib/python-exec/python3.14/solaar"]
    )
    assert _is_solaar_background_cmdline(["solaar"])
    assert _is_solaar_background_cmdline(["/usr/bin/solaar-gui"])
    assert _is_solaar_background_cmdline(["python3", "-m", "solaar"])
    # Background app options (e.g. --window=hide) are not CLI verbs.
    assert _is_solaar_background_cmdline(["solaar", "--window=hide"])


def test_env_wrapped_solaar_matches():
    # Autostart entries often launch Solaar via /usr/bin/env (with optional
    # VAR=val assignments / env options). The env wrapper must be unwrapped so
    # these still count as the background app.
    assert _is_solaar_background_cmdline(["/usr/bin/env", "solaar"])
    assert _is_solaar_background_cmdline(["env", "python3", "-m", "solaar"])
    assert _is_solaar_background_cmdline(["/usr/bin/env", "FOO=bar", "solaar"])
    assert _is_solaar_background_cmdline(
        ["env", "-u", "SOMEVAR", "python3", "/path/to/solaar"]
    )
    # An env-wrapped CLI verb still does NOT count (it is transient).
    assert not _is_solaar_background_cmdline(["/usr/bin/env", "solaar", "show"])
    # env wrapping an unrelated program still does not match.
    assert not _is_solaar_background_cmdline(["/usr/bin/env", "firefox"])


def test_cli_invocations_do_not_match():
    # Transient `solaar config`/`solaar show` CLI calls do NOT run rules.
    assert not _is_solaar_background_cmdline(["solaar", "config", "dev", "x"])
    assert not _is_solaar_background_cmdline(["solaar", "show"])
    assert not _is_solaar_background_cmdline(["python3", "-m", "solaar", "config", "x"])


def test_our_own_daemon_does_not_match():
    # Never match this daemon (python -m mx4d).
    assert not _is_solaar_background_cmdline(["python3.14", "-m", "mx4d"])
    assert not _is_solaar_background_cmdline(["/usr/bin/python3", "/x/mx4d"])
    assert not _is_solaar_background_cmdline([])
    # An unrelated process must not match.
    assert not _is_solaar_background_cmdline(["/usr/bin/firefox"])


# -- solaar_running over a mocked process list -------------------------------


def _fake_procs(monkeypatch, table):
    monkeypatch.setattr(solaarmod, "_iter_proc_cmdlines", lambda: iter(table))


def test_solaar_running_present(monkeypatch):
    _fake_procs(
        monkeypatch,
        [
            (111, ["/usr/bin/firefox"]),
            (5673, ["/usr/bin/python3.14", "/usr/lib/.../solaar"]),
        ],
    )
    assert solaar_running() is True


def test_solaar_running_absent(monkeypatch):
    _fake_procs(monkeypatch, [(111, ["/usr/bin/firefox"]), (222, ["bash"])])
    assert solaar_running() is False


def test_solaar_running_only_our_process(monkeypatch):
    # Only this daemon + a transient solaar CLI -> NOT "Solaar present".
    _fake_procs(
        monkeypatch,
        [
            (333, ["python3.14", "-m", "mx4d"]),
            (444, ["solaar", "show"]),
        ],
    )
    assert solaar_running() is False


def test_solaar_running_no_proc(monkeypatch):
    # No /proc (non-Linux / restricted) -> False, never raises.
    def boom():
        raise OSError("no /proc")

    monkeypatch.setattr(solaarmod, "_iter_proc_cmdlines", lambda: iter(()))
    assert solaar_running() is False


# -- the auto decision: auto/true capture the panel, false defers to Solaar ----
# (auto captures even under Solaar — via fire-and-forget writes — because tap vs.
# hold needs the raw events, which a Solaar rule cannot provide.)


def _daemon_with_mode(mode):
    cfg = default_config()
    cfg.divert_panel = mode
    return Mx4Daemon(config=cfg)


def test_auto_captures_when_solaar_present(monkeypatch):
    monkeypatch.setattr("mx4d.daemon.solaar_running", lambda: True)
    daemon = _daemon_with_mode(DIVERT_AUTO)
    # Capture (so tap/hold work); setup() sends the divert fire-and-forget here.
    assert daemon._resolve_divert() is True


def test_auto_captures_when_solaar_absent(monkeypatch):
    monkeypatch.setattr("mx4d.daemon.solaar_running", lambda: False)
    daemon = _daemon_with_mode(DIVERT_AUTO)
    assert daemon._resolve_divert() is True  # standalone capture


def test_true_always_captures(monkeypatch):
    # Forced standalone: divert even if Solaar is running.
    monkeypatch.setattr("mx4d.daemon.solaar_running", lambda: True)
    daemon = _daemon_with_mode(DIVERT_TRUE)
    assert daemon._resolve_divert() is True


def test_false_never_captures(monkeypatch):
    # Forced Solaar-first: never divert even if Solaar is absent.
    monkeypatch.setattr("mx4d.daemon.solaar_running", lambda: False)
    daemon = _daemon_with_mode(DIVERT_FALSE)
    assert daemon._resolve_divert() is False
