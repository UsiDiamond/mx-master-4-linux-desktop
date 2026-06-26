"""Unit tests for config defaults, persistence, and task-manager detection."""

from __future__ import annotations

import os

from mx4d import config as cfgmod
from mx4d.config import (
    DIVERT_AUTO,
    DIVERT_FALSE,
    DIVERT_TRUE,
    TASK_MANAGER_FALLBACK,
    default_config,
    detect_task_manager,
    load_config,
    parse_divert_panel,
)
from mx4d.sources import KIND_FOCUS, KIND_NOTIFICATION, KIND_SOUND


def test_defaults():
    c = default_config()
    assert c.ambient_enabled is True
    assert c.quiet_hours_enabled is False
    # divert_panel is now a TRI-STATE; the default is "auto" (defer to Solaar).
    assert c.divert_panel == DIVERT_AUTO
    # Trigger default is a firmware-supported waveform (COMPLETED is NOT in the
    # observed MX4 capability mask 0x0001003C).
    assert c.trigger_waveform == "HAPPY_ALERT"
    # per-source defaults
    assert c.source(KIND_NOTIFICATION).enabled is True
    assert c.source(KIND_NOTIFICATION).waveform == "HAPPY_ALERT"
    assert c.source(KIND_FOCUS).waveform == "SUBTLE_COLLISION"
    assert c.source(KIND_SOUND).enabled is False  # opt-in
    assert c.source(KIND_SOUND).waveform == "DAMP_COLLISION"
    # radial center action is non-empty (auto-detected).
    assert c.radial_center_action
    # Phase-3 integration keys default sanely.
    assert c.radial_default_menu == "default"
    assert c.overlay_command == "mx4-radial"


def test_overlay_and_default_menu_roundtrip(tmp_path, monkeypatch):
    # Custom [overlay] command + [radial] default_menu survive load and a save.
    path = tmp_path / "config.ini"
    path.write_text(
        "[overlay]\ncommand = /opt/mx4/mx4-radial\n[radial]\ndefault_menu = work\n",
        encoding="utf-8",
    )
    c = load_config(str(path))
    assert c.overlay_command == "/opt/mx4/mx4-radial"
    assert c.radial_default_menu == "work"
    c.save(str(path))
    reloaded = load_config(str(path))
    assert reloaded.overlay_command == "/opt/mx4/mx4-radial"
    assert reloaded.radial_default_menu == "work"


def test_overlay_command_falls_back_to_default_when_blank(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("[overlay]\ncommand =\n", encoding="utf-8")
    c = load_config(str(path))
    assert c.overlay_command == "mx4-radial"


def test_detect_task_manager_prefers_present_binary(monkeypatch):
    # Pretend only qps is present -> LXQt monitor chosen.
    monkeypatch.setattr(
        cfgmod.shutil,
        "which",
        lambda name: "/usr/bin/qps" if name == "qps" else None,
    )
    assert detect_task_manager() == "qps"


def test_detect_task_manager_plasma_wins(monkeypatch):
    present = {"plasma-systemmonitor", "qps"}
    monkeypatch.setattr(
        cfgmod.shutil,
        "which",
        lambda name: ("/usr/bin/" + name) if name in present else None,
    )
    # KDE is first in the candidate order.
    assert detect_task_manager() == "plasma-systemmonitor"


def test_detect_task_manager_fallback(monkeypatch):
    # Nothing present -> documented xterm/htop fallback (string returned even
    # when neither exists, so config is never empty).
    monkeypatch.setattr(cfgmod.shutil, "which", lambda name: None)
    assert detect_task_manager() == TASK_MANAGER_FALLBACK


def test_roundtrip_save_load(tmp_path):
    path = os.path.join(tmp_path, "config.ini")
    c = load_config(path)  # writes defaults
    assert os.path.exists(path)
    c.divert_panel = DIVERT_FALSE
    c.source(KIND_NOTIFICATION).waveform = "JINGLE"
    c.save(path)

    reloaded = load_config(path)
    assert reloaded.divert_panel == DIVERT_FALSE
    assert reloaded.source(KIND_NOTIFICATION).waveform == "JINGLE"


def test_radial_center_command_key_matches_overlay(tmp_path):
    # The daemon must write the SAME INI key the C++ overlay's MenuConfig reads
    # ("center/command" under [radial]) so a user edit affects both processes.
    path = os.path.join(tmp_path, "config.ini")
    load_config(path)  # writes defaults
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "center/command" in text


def test_radial_center_action_legacy_key_still_read(tmp_path):
    # Backward compat: a file using the old "center_action" key still loads.
    path = os.path.join(tmp_path, "config.ini")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[radial]\ncenter_action = my-custom-monitor\n")
    c = load_config(path, write_defaults=False)
    assert c.radial_center_action == "my-custom-monitor"


def test_radial_center_command_preferred_over_legacy(tmp_path):
    path = os.path.join(tmp_path, "config.ini")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "[radial]\ncenter/command = new-monitor\ncenter_action = old-monitor\n"
        )
    c = load_config(path, write_defaults=False)
    assert c.radial_center_action == "new-monitor"


def test_radial_center_label_icon_survive_daemon_save(tmp_path):
    # The config GUI is the authority for the center label/icon. A custom value
    # must survive a daemon (re)write of the file — the daemon must NOT clobber
    # it with the hardcoded "Task Manager"/"utilities-system-monitor" defaults.
    path = os.path.join(tmp_path, "config.ini")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "[radial]\n"
            "center/command = kcalc --hex\n"
            "center/label = Calculator\n"
            "center/icon = accessories-calculator\n"
        )
    c = load_config(path, write_defaults=False)
    assert c.radial_center_label == "Calculator"
    assert c.radial_center_icon == "accessories-calculator"
    c.save(path)
    reloaded = load_config(path, write_defaults=False)
    assert reloaded.radial_center_label == "Calculator"
    assert reloaded.radial_center_icon == "accessories-calculator"
    assert reloaded.radial_center_action == "kcalc --hex"


def test_parse_divert_panel_tristate():
    assert parse_divert_panel("auto") == DIVERT_AUTO
    assert parse_divert_panel(" AUTO ") == DIVERT_AUTO
    # Bool back-compat: every legacy truthy/falsy spelling maps exactly.
    for truthy in ("true", "True", "1", "yes", "on"):
        assert parse_divert_panel(truthy) == DIVERT_TRUE
    for falsy in ("false", "False", "0", "no", "off"):
        assert parse_divert_panel(falsy) == DIVERT_FALSE
    # Unrecognised / empty -> safe default "auto" (never silently disables).
    assert parse_divert_panel("") == DIVERT_AUTO
    assert parse_divert_panel("garbage") == DIVERT_AUTO


def test_divert_panel_bool_backcompat_load(tmp_path):
    # An existing config with the legacy bool value behaves EXACTLY as before.
    path = os.path.join(tmp_path, "config.ini")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[trigger]\ndivert_panel = true\n")
    assert load_config(path, write_defaults=False).divert_panel == DIVERT_TRUE
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[trigger]\ndivert_panel = false\n")
    assert load_config(path, write_defaults=False).divert_panel == DIVERT_FALSE


def test_divert_panel_auto_roundtrip(tmp_path):
    # "auto" must survive load + save (a bool toggle would lose it as "false").
    path = os.path.join(tmp_path, "config.ini")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[trigger]\ndivert_panel = auto\n")
    c = load_config(path, write_defaults=False)
    assert c.divert_panel == DIVERT_AUTO
    c.save(path)
    with open(path, encoding="utf-8") as fh:
        assert "divert_panel = auto" in fh.read()
    assert load_config(path, write_defaults=False).divert_panel == DIVERT_AUTO


def test_default_config_writes_auto(tmp_path):
    # A first-run default file documents/writes "auto".
    path = os.path.join(tmp_path, "config.ini")
    load_config(path)  # writes defaults
    with open(path, encoding="utf-8") as fh:
        assert "divert_panel = auto" in fh.read()


def test_trigger_hold_and_menu_defaults_roundtrip(tmp_path):
    # Hold threshold + per-gesture menu ids default sanely and survive a save.
    c = default_config()
    assert c.trigger_hold_threshold == 0.4
    assert c.trigger_tap_menu == ""  # empty -> the default menu
    assert c.trigger_hold_menu == ""
    path = os.path.join(tmp_path, "config.ini")
    c.trigger_hold_threshold = 0.6
    c.trigger_tap_menu = "apps"
    c.trigger_hold_menu = "tasks"
    c.save(path)
    reloaded = load_config(path, write_defaults=False)
    assert reloaded.trigger_hold_threshold == 0.6
    assert reloaded.trigger_tap_menu == "apps"
    assert reloaded.trigger_hold_menu == "tasks"


def test_unknown_keys_preserved(tmp_path):
    path = os.path.join(tmp_path, "config.ini")
    load_config(path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n[custom]\nfoo = bar\n")
    c = load_config(path)
    c.save(path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "[custom]" in text and "foo = bar" in text
