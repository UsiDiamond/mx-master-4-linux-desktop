"""Unit tests for the HapticEngine: play packet, bitmask gating, level, debounce."""

from __future__ import annotations

import time

from mx4d.haptics import (
    PLAY_FUNC_BYTE,
    WAVEFORMS,
    HapticEngine,
    resolve_waveform,
)


def test_play_func_byte_constant():
    assert PLAY_FUNC_BYTE == 0x4E


def test_waveform_table():
    # Spot-check the documented sparse table.
    assert WAVEFORMS["SHARP_STATE_CHANGE"] == 0x00
    assert WAVEFORMS["SUBTLE_COLLISION"] == 0x04
    assert WAVEFORMS["COMPLETED"] == 0x07
    assert WAVEFORMS["WHISPER_COLLISION"] == 0x1B


def test_resolve_waveform():
    assert resolve_waveform("COMPLETED") == 0x07
    assert resolve_waveform("subtle collision") == 0x04
    assert resolve_waveform(0x07) == 0x07
    assert resolve_waveform("0x1B") == 0x1B


def test_build_play_packet_contract(transport):
    # play packet for waveform w on device d / feature index F:
    #   [0x10, d, F, 0x4E, w, 0, 0]
    engine = HapticEngine(transport, 0x0B)
    packet = engine.build_play_packet("COMPLETED")
    assert packet == bytes([0x10, transport.device_index, 0x0B, 0x4E, 0x07, 0, 0])


def test_capability_gating(transport, fake_device):
    # The fake supports waveforms 0..7 plus bit 0x0B (mask 0x000008FF).
    engine = HapticEngine(transport, 0x0B)
    engine.read_capabilities()
    assert engine.supports("COMPLETED")  # 0x07 -> supported
    assert engine.supports("SUBTLE_COLLISION")  # 0x04 -> supported
    assert engine.supports("MAD")  # 0x0B -> supported (bit set in fake mask)
    assert not engine.supports("RINGING")  # 0x0E -> not in mask
    assert not engine.supports("WHISPER_COLLISION")  # 0x1B -> not in mask


def test_play_gated_when_unsupported(transport, fake_device):
    engine = HapticEngine(transport, 0x0B)
    engine.read_capabilities()
    # Unsupported waveform with strict gating must not be written.
    assert engine.play("RINGING", force=True, fallback=False) is False
    time.sleep(0.05)
    # No new play packet should have been sent (capability read happened earlier).
    plays = [r for r in fake_device.requests if r[0] == 0x10 and r[3] == 0x4E]
    assert not plays


def test_play_fallback_substitutes_supported(transport, fake_device):
    # RINGING (0x0E) is unsupported in the fake mask; with fallback the engine
    # plays a supported waveform (HAPPY_ALERT 0x05 is in the fake mask) instead.
    engine = HapticEngine(transport, 0x0B)
    engine.read_capabilities()
    assert engine.play("RINGING", force=True, fallback=True) is True
    time.sleep(0.05)
    plays = [r for r in fake_device.requests if r[0] == 0x10 and r[3] == 0x4E]
    assert plays
    # The played waveform must be one the device actually supports.
    assert engine.supports(plays[-1][4])


def test_play_supported_writes_packet(transport, fake_device):
    engine = HapticEngine(transport, 0x0B)
    engine.read_capabilities()
    assert engine.play("COMPLETED", force=True) is True
    time.sleep(0.05)
    plays = [r for r in fake_device.requests if r[0] == 0x10 and r[3] == 0x4E]
    assert plays and plays[-1][4] == 0x07


def test_debounce(transport, fake_device):
    engine = HapticEngine(transport, 0x0B, min_interval=0.5)
    engine.read_capabilities()
    assert engine.play("COMPLETED") is True
    # Immediate second play is debounced (no force).
    assert engine.play("COMPLETED") is False
    # force bypasses debounce.
    assert engine.play("COMPLETED", force=True) is True


def test_should_play_debounce(transport, fake_device):
    # should_play() claims the debounce window atomically and does NO device I/O,
    # so the daemon can drop a coalesced burst before issuing any HID round-trip.
    engine = HapticEngine(transport, 0x0B, min_interval=0.5)
    before = len(fake_device.requests)
    assert engine.should_play() is True  # first event passes
    assert engine.should_play() is False  # immediate second is debounced
    # No requests were sent to the device by the gate itself.
    assert len(fake_device.requests) == before
    time.sleep(0.55)
    assert engine.should_play() is True  # window elapsed -> passes again


def test_get_set_level(transport):
    engine = HapticEngine(transport, 0x0B)
    assert engine.get_level() == 60
    assert engine.is_enabled() is True
    engine.set_level(45)  # acked by fake; no raise == success
