"""Detect a running Solaar so the daemon can defer the Actions Ring trigger.

The addon is **Solaar-first with a self-sufficient standalone fallback**: when a
Solaar *background* process is running it already owns the device, so our daemon
must NOT divert the Actions Ring panel (Solaar's rule fires ``ShowMenu``). When
Solaar is absent the standalone path diverts + captures the panel itself.

This module is intentionally dependency-light: it never imports
``logitech_receiver`` or any Solaar code — it just scans ``/proc`` for a Solaar
background process. That keeps the standalone path zero-dependency and makes the
detection cheap and reliable whether or not Solaar is installed.

What counts as "Solaar running":

* a process whose command line invokes the Solaar **GUI/background** program
  (``solaar`` / ``solaar-gui`` / ``python -m solaar`` with no CLI verb), i.e. the
  long-lived tray app that holds the device. A leading ``/usr/bin/env`` wrapper
  (with any ``VAR=val`` assignments / options) is unwrapped first, so autostart
  entries like ``env solaar`` / ``env python3 -m solaar`` still count.

What does NOT count (so we never defer to something that won't fire the rule):

* this very daemon (``mx4d``) — never match ourselves;
* a transient ``solaar config`` / ``solaar show`` / other ``solaar <verb>`` CLI
  invocation — these are short-lived and do not run rules.

Robust when Solaar is not installed: returns ``False`` and never raises.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Solaar CLI verbs (the first non-option argument after the program name). A
# command line carrying one of these is a transient CLI invocation that does NOT
# run rules, so it must not count as "Solaar present".
_SOLAAR_CLI_VERBS = frozenset(
    {
        "config",
        "show",
        "probe",
        "pair",
        "unpair",
        "device",
        "profiles",
    }
)


def _basename_no_ext(token: str) -> str:
    """Return the lowercased basename of ``token`` without a trailing suffix.

    Handles absolute paths (``/usr/bin/solaar``) and interpreter-suffixed names
    (``solaar-gui``, ``solaar.py``).
    """
    name = os.path.basename(token).lower()
    if name.endswith(".py"):
        name = name[:-3]
    return name


def _strip_env_prefix(args: list[str]) -> list[str]:
    """Strip a leading ``env`` wrapper and its ``VAR=val`` / option arguments.

    Desktop autostart entries frequently launch Solaar via ``/usr/bin/env`` (e.g.
    ``env solaar`` or ``env python3 -m solaar``), sometimes with environment
    assignments (``env FOO=bar solaar``) or options (``env -u VAR solaar``). We
    drop the ``env`` token and everything up to the first plain program token so
    the rest of the classifier sees the real program (which may itself be
    ``python ...`` or ``solaar``). Anything that is not an ``env`` wrapper is
    returned unchanged.
    """
    if not args or _basename_no_ext(args[0]) != "env":
        return args
    idx = 1
    while idx < len(args):
        tok = args[idx]
        # Options that consume the NEXT token (env -u NAME / -S string / -C dir).
        if tok in ("-u", "--unset", "-S", "--split-string", "-C", "--chdir"):
            idx += 2
            continue
        # Other dash-options (e.g. -i / --ignore-environment) consume only self.
        if tok.startswith("-"):
            idx += 1
            continue
        # A ``VAR=value`` assignment precedes the program; skip it.
        if "=" in tok:
            idx += 1
            continue
        break  # the program token
    return args[idx:]


def _is_solaar_background_cmdline(args: list[str]) -> bool:
    """Decide whether a process ``args`` is a long-lived Solaar background app.

    ``args`` is the NUL-split ``/proc/<pid>/cmdline`` already decoded to a list of
    strings. Matches ``solaar`` / ``solaar-gui`` (optionally launched as
    ``python .../solaar`` or ``python -m solaar``, and optionally wrapped in
    ``/usr/bin/env``) but rejects ``solaar <cli-verb>`` and rejects our own daemon.
    """
    # Unwrap a leading ``env`` (with any VAR=val / options) so we classify the
    # real program, not the env shim.
    args = _strip_env_prefix(args)
    if not args:
        return False

    # Drop a leading interpreter (python / python3 / python3.14 / pythonX.Y) and
    # its options so we look at the actual program token. ``python -m solaar``
    # surfaces "solaar" as the module after ``-m``.
    idx = 0
    first = _basename_no_ext(args[0])
    if first.startswith("python"):
        idx = 1
        # Walk past interpreter options; ``-m solaar`` means the module is solaar.
        while idx < len(args):
            tok = args[idx]
            if tok == "-m":
                if idx + 1 < len(args):
                    mod = args[idx + 1].lower()
                    if mod == "solaar" or mod.startswith("solaar."):
                        return not _has_cli_verb(args[idx + 2 :])
                return False
            if tok.startswith("-"):
                idx += 1
                continue
            break  # the script path

    if idx >= len(args):
        return False

    prog = _basename_no_ext(args[idx])
    # Never match ourselves (the mx4 daemon runs as ``python -m mx4d``).
    if prog in ("mx4d", "__main__"):
        return False
    if prog == "solaar" or prog == "solaar-gui":
        # ``solaar`` / ``solaar-gui`` with no CLI verb is the background app.
        return not _has_cli_verb(args[idx + 1 :])
    return False


def _has_cli_verb(rest: list[str]) -> bool:
    """Return True if ``rest`` (args after the program) begins with a CLI verb.

    The first non-option token is the Solaar sub-command; ``solaar config ...`` /
    ``solaar show`` are transient and must not count as the background app.
    """
    for tok in rest:
        if tok.startswith("-"):
            continue  # an option to the background app (e.g. --window=hide)
        return tok.lower() in _SOLAAR_CLI_VERBS
    return False


def _iter_proc_cmdlines():
    """Yield ``(pid, args)`` for every readable process, skipping our own.

    ``args`` is the decoded, NUL-split ``/proc/<pid>/cmdline``. Unreadable or
    vanished processes are skipped silently. Returns nothing (and never raises)
    on a system without ``/proc``.
    """
    own_pid = os.getpid()
    try:
        pids = os.listdir("/proc")
    except OSError:
        return  # no /proc (non-Linux / restricted) -> caller sees "absent"
    for entry in pids:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own_pid:
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as fh:
                raw = fh.read()
        except (OSError, ValueError):
            continue  # process vanished / not permitted
        if not raw:
            continue
        args = [a for a in raw.decode("utf-8", "replace").split("\0") if a]
        if args:
            yield pid, args


def solaar_running() -> bool:
    """Return whether a long-lived Solaar background process is running.

    Cheap, dependency-light heuristic: scan ``/proc`` for a process whose command
    line is the Solaar GUI/background app (excluding this daemon and transient
    ``solaar <verb>`` CLI calls). Returns ``False`` — never raises — when Solaar
    is not installed or ``/proc`` is unavailable.
    """
    for pid, args in _iter_proc_cmdlines():
        if _is_solaar_background_cmdline(args):
            logger.debug("detected Solaar background process pid=%d", pid)
            return True
    return False
