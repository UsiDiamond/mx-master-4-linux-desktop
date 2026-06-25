#pragma once
#include <cstdint>

class HidppDevice;

/// Driver for HID++ feature 0x19B0 — HAPTIC FEEDBACK.
///
/// Proven on MX Master 4 with feature index 0x0B (discovered at runtime via ROOT).
///
/// Functions used:
///   0x00  getCapabilities — returns a waveform capability bitmask (3 bytes)
///   0x10  getHapticLevel  — current motor drive level (0-100)
///   0x20  setHapticLevel  — set motor drive level
///   0x40  playWaveform    — trigger one waveform
///
/// Waveform indices (sparse; capability bitmask governs which are supported):
///   0x00 SHARP_STATE_CHANGE   0x04 SUBTLE_COLLISION   0x08 SQUARE
///   0x01 DAMP_STATE_CHANGE    0x05 HAPPY_ALERT        0x09 WAVE
///   0x02 SHARP_COLLISION      0x06 ANGRY_ALERT        0x0A FIREWORK
///   0x03 DAMP_COLLISION       0x07 COMPLETED          0x0B MAD
///   0x0C KNOCK                0x0D JINGLE             0x0E RINGING
///   0x1B WHISPER_COLLISION
class HapticsFeature {
public:
    static constexpr uint16_t FEATURE_NUMBER = 0x19B0;

    // Waveform constants (use these in daemon code rather than raw ints)
    enum Waveform : uint8_t {
        SharpStateChange  = 0x00,
        DampStateChange   = 0x01,
        SharpCollision    = 0x02,
        DampCollision     = 0x03,
        SubtleCollision   = 0x04,
        HappyAlert        = 0x05,
        AngryAlert        = 0x06,
        Completed         = 0x07,
        Square            = 0x08,
        Wave              = 0x09,
        Firework          = 0x0A,
        Mad               = 0x0B,
        Knock             = 0x0C,
        Jingle            = 0x0D,
        Ringing           = 0x0E,
        WhisperCollision  = 0x1B,
    };

    /// @param featureIndex  Runtime index resolved via FeatureIndex::resolve()
    explicit HapticsFeature(uint8_t featureIndex);

    /// Trigger a haptic waveform (HID++ fn 0x40).
    ///
    /// Mirrors the Python proof-of-concept exactly:
    ///   long report [0x11, deviceIdx, featureIdx, 0x4E, waveform, 0x00 …]
    ///
    /// @param dev        Open HidppDevice
    /// @param waveform   Waveform index (see Waveform enum)
    /// @param intensity  Motor level override 0-100 for this play only; 0 = use stored level
    /// @return true on success
    [[nodiscard]] bool playWaveform(HidppDevice& dev,
                                    uint8_t waveform,
                                    uint8_t intensity = 60);

    /// Set the persistent haptic motor level (HID++ fn 0x20).
    ///
    /// @param dev    Open HidppDevice
    /// @param level  0-100; the device stores this across power cycles
    [[nodiscard]] bool setLevel(HidppDevice& dev, uint8_t level);

    /// Query the current stored level (HID++ fn 0x10).
    ///
    /// @return level 0-100, or -1 on failure
    [[nodiscard]] int getLevel(HidppDevice& dev);

private:
    uint8_t m_featureIndex;
};
