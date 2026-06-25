"""Configuration: INI at ``~/.config/mx4desktop/config.ini`` with sane defaults.

The config drives the daemon entirely: master enable, per-source waveform +
intensity + enable, trigger behaviour, quiet hours, and a ``[radial]`` section
whose default center action launches the auto-detected task manager / system
monitor for the running desktop environment.

The file is created with defaults on first run and never silently overwritten;
unknown keys are preserved on save.
"""

from __future__ import annotations

import configparser
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Optional

from .sources import KIND_FOCUS, KIND_NOTIFICATION, KIND_SOUND

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "mx4desktop",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.ini")


# Ordered task-manager candidates: (binary, full command). The center radial
# action defaults to the first candidate whose binary is present. KDE first,
# then LXQt, then generic, then a terminal htop as the universal fallback.
TASK_MANAGER_CANDIDATES: list[tuple[str, str]] = [
    ("plasma-systemmonitor", "plasma-systemmonitor"),
    ("qps", "qps"),
    ("lxtask", "lxtask"),
    ("gnome-system-monitor", "gnome-system-monitor"),
    ("ksysguard", "ksysguard"),
]
# Final fallback always works if a terminal + htop exist; if not, still returned
# as the documented default so the config is never empty.
TASK_MANAGER_FALLBACK = "xterm -e htop"


def detect_task_manager() -> str:
    """Return a command to launch the system task manager / monitor.

    Probes :data:`TASK_MANAGER_CANDIDATES` in order (KDE -> LXQt -> generic) and
    returns the first whose binary is on ``PATH``; otherwise ``xterm -e htop``.
    """
    for binary, command in TASK_MANAGER_CANDIDATES:
        if shutil.which(binary) is not None:
            return command
    # Prefer the documented terminal fallback only if both parts exist.
    if shutil.which("xterm") is not None and shutil.which("htop") is not None:
        return TASK_MANAGER_FALLBACK
    if shutil.which("htop") is not None:
        return "htop"
    return TASK_MANAGER_FALLBACK


@dataclass
class SourceConfig:
    """Per-source haptic mapping."""

    enabled: bool
    waveform: str
    intensity: int  # 0..100 master level applied while this source plays


@dataclass
class Mx4Config:
    """Typed view over the INI file."""

    # [ambient]
    ambient_enabled: bool
    quiet_hours_enabled: bool
    debounce_interval: float
    # per-source
    sources: dict[str, SourceConfig]
    # [trigger]
    divert_panel: bool
    trigger_waveform: str
    # [radial]
    radial_center_action: str
    radial_center_label: str
    radial_center_icon: str
    radial_default_menu: str
    # [overlay]
    overlay_command: str
    # raw parser kept so unknown keys survive a save().
    _parser: configparser.ConfigParser

    # -- per-source helpers ---------------------------------------------
    def source(self, kind: str) -> SourceConfig:
        """Return the :class:`SourceConfig` for a source kind."""
        return self.sources[kind]

    # -- persistence -----------------------------------------------------
    def save(self, path: str = CONFIG_PATH) -> None:
        """Write the current values back to ``path`` (creating the dir)."""
        # Sync dataclass fields back into the parser before writing.
        p = self._parser
        _set(p, "ambient", "enabled", _b(self.ambient_enabled))
        _set(p, "ambient", "quiet_hours", _b(self.quiet_hours_enabled))
        _set(p, "ambient", "debounce_interval", str(self.debounce_interval))
        for kind, sc in self.sources.items():
            section = "source:%s" % kind
            _set(p, section, "enabled", _b(sc.enabled))
            _set(p, section, "waveform", sc.waveform)
            _set(p, section, "intensity", str(sc.intensity))
        _set(p, "trigger", "divert_panel", _b(self.divert_panel))
        _set(p, "trigger", "waveform", self.trigger_waveform)
        # Use the SAME key the C++ overlay reads (QSettings "center/command")
        # so a user editing the shared INI affects both processes. The legacy
        # "center_action" key is still read on load for backward compatibility.
        _set(p, "radial", "center/command", self.radial_center_action)
        # Preserve the GUI-set center label/icon (the config GUI is the authority
        # for these). Do NOT hardcode them, or a user's custom center label/icon
        # is silently lost whenever the daemon (re)writes the file.
        _set(p, "radial", "center/label", self.radial_center_label)
        _set(p, "radial", "center/icon", self.radial_center_icon)
        _set(p, "radial", "default_menu", self.radial_default_menu)
        # [overlay]: how the daemon lazily launches the radial overlay process.
        _set(p, "overlay", "command", self.overlay_command)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            p.write(fh)
        logger.debug("saved config to %s", path)


def _b(value: bool) -> str:
    return "true" if value else "false"


def _set(parser: configparser.ConfigParser, section: str, key: str, value: str) -> None:
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, key, value)


def _default_parser() -> configparser.ConfigParser:
    """Build a parser pre-populated with all default values."""
    p = configparser.ConfigParser()
    p["ambient"] = {
        "enabled": "true",
        "quiet_hours": "false",
        "debounce_interval": "0.12",
    }
    # Per-source defaults: notification (alert), focus (subtle), sound (knock).
    p["source:%s" % KIND_NOTIFICATION] = {
        "enabled": "true",
        "waveform": "HAPPY_ALERT",
        # critical-urgency notifications upgrade to SHARP_COLLISION in the daemon
        # (see daemon.py CRITICAL_WAVEFORM).
        "intensity": "70",
    }
    p["source:%s" % KIND_FOCUS] = {
        "enabled": "true",
        "waveform": "SUBTLE_COLLISION",
        "intensity": "40",
    }
    p["source:%s" % KIND_SOUND] = {
        "enabled": "false",  # opt-in; coarse + often redundant with notifications
        # KNOCK (0x0C) is not present on observed MX4 firmware; DAMP_COLLISION
        # is. The engine still falls back at runtime if a waveform is missing.
        "waveform": "DAMP_COLLISION",
        "intensity": "50",
    }
    p["trigger"] = {
        "divert_panel": "true",
        # COMPLETED (0x07) is NOT supported by the observed MX4 firmware
        # (capability mask 0x0001003C). HAPPY_ALERT is, and reads as a clear
        # confirmation tick; the engine also falls back if this is unsupported.
        "waveform": "HAPPY_ALERT",
    }
    # Shared with the C++ overlay's MenuConfig (QSettings "center/command").
    p["radial"] = {
        "center/command": detect_task_manager(),
        "center/label": "Task Manager",
        "center/icon": "utilities-system-monitor",
        # Menu id the daemon passes to Overlay.Show() on a trigger press; the
        # overlay maps "default" -> [radial], any other id -> [radial:<id>].
        "default_menu": "default",
    }
    # How the daemon launches the overlay process when its bus name is absent.
    # Default is the bare binary name (resolved on PATH, e.g. installed to
    # ~/.local/bin/mx4-radial); an absolute path is accepted for dev/testing.
    p["overlay"] = {
        "command": "mx4-radial",
    }
    return p


def _build(parser: configparser.ConfigParser) -> Mx4Config:
    """Construct a typed :class:`Mx4Config` from a parser (filling defaults)."""
    defaults = _default_parser()

    def get(section: str, key: str, fallback: Optional[str] = None) -> str:
        if parser.has_option(section, key):
            return parser.get(section, key)
        if fallback is not None:
            return fallback
        return defaults.get(section, key)

    def getbool(section: str, key: str) -> bool:
        return get(section, key).strip().lower() in ("1", "true", "yes", "on")

    def getint(section: str, key: str) -> int:
        try:
            return int(get(section, key))
        except ValueError:
            return int(defaults.get(section, key))

    def getfloat(section: str, key: str) -> float:
        try:
            return float(get(section, key))
        except ValueError:
            return float(defaults.get(section, key))

    sources: dict[str, SourceConfig] = {}
    for kind in (KIND_NOTIFICATION, KIND_FOCUS, KIND_SOUND):
        section = "source:%s" % kind
        sources[kind] = SourceConfig(
            enabled=getbool(section, "enabled"),
            waveform=get(section, "waveform"),
            intensity=getint(section, "intensity"),
        )

    # Radial center action. Prefer the overlay-shared "center/command" key, fall
    # back to the legacy "center_action", and finally auto-detect if both are
    # absent/empty so the contract (center == task manager) always holds.
    center = get("radial", "center/command", fallback="").strip()
    if not center:
        center = get("radial", "center_action", fallback="").strip()
    if not center:
        center = detect_task_manager()

    center_label = get("radial", "center/label", fallback="").strip() or "Task Manager"
    center_icon = (
        get("radial", "center/icon", fallback="").strip()
        or "utilities-system-monitor"
    )
    default_menu = get("radial", "default_menu", fallback="").strip() or "default"
    overlay_command = get("overlay", "command", fallback="").strip() or "mx4-radial"

    return Mx4Config(
        ambient_enabled=getbool("ambient", "enabled"),
        quiet_hours_enabled=getbool("ambient", "quiet_hours"),
        debounce_interval=getfloat("ambient", "debounce_interval"),
        sources=sources,
        divert_panel=getbool("trigger", "divert_panel"),
        trigger_waveform=get("trigger", "waveform"),
        radial_center_action=center,
        radial_center_label=center_label,
        radial_center_icon=center_icon,
        radial_default_menu=default_menu,
        overlay_command=overlay_command,
        _parser=parser,
    )


def default_config() -> Mx4Config:
    """Return a config populated entirely with defaults (no file I/O)."""
    return _build(_default_parser())


def load_config(path: str = CONFIG_PATH, *, write_defaults: bool = True) -> Mx4Config:
    """Load the config from ``path``, creating it with defaults if absent.

    :param write_defaults: write a fully-populated default file on first run so
        users have something to edit.
    """
    parser = configparser.ConfigParser()
    if os.path.exists(path):
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error) as exc:
            logger.warning("could not read %s (%s); using defaults", path, exc)
            parser = configparser.ConfigParser()
    config = _build(parser)
    if write_defaults and not os.path.exists(path):
        try:
            config.save(path)
            logger.info("wrote default config to %s", path)
        except OSError as exc:
            logger.warning("could not write default config: %s", exc)
    return config
