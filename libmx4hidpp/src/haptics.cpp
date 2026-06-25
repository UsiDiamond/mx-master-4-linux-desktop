#include "mx4hidpp/haptics.h"
#include "mx4hidpp/hidpp_device.h"

#include <array>
#include <vector>

// HID++ function nibbles for feature 0x19B0
static constexpr uint8_t FN_GET_CAPABILITIES = 0x00;
static constexpr uint8_t FN_GET_LEVEL        = 0x10;
static constexpr uint8_t FN_SET_LEVEL        = 0x20;
static constexpr uint8_t FN_PLAY_WAVEFORM    = 0x40;

// ---------------------------------------------------------------------------

HapticsFeature::HapticsFeature(uint8_t featureIndex)
    : m_featureIndex(featureIndex)
{}

// ---------------------------------------------------------------------------

bool HapticsFeature::playWaveform(HidppDevice& dev,
                                   uint8_t waveform,
                                   uint8_t intensity)
{
    // Payload: [waveform, intensity, 0x00 ...] (13 bytes padded by sendAndReceive)
    const std::array<uint8_t, 2> payload{waveform, intensity};
    std::vector<uint8_t> response;
    return dev.sendAndReceive(m_featureIndex, FN_PLAY_WAVEFORM, payload, response);
}

// ---------------------------------------------------------------------------

bool HapticsFeature::setLevel(HidppDevice& dev, uint8_t level)
{
    // Clamp to valid range
    if (level > 100) level = 100;
    const std::array<uint8_t, 1> payload{level};
    std::vector<uint8_t> response;
    return dev.sendAndReceive(m_featureIndex, FN_SET_LEVEL, payload, response);
}

// ---------------------------------------------------------------------------

int HapticsFeature::getLevel(HidppDevice& dev)
{
    const std::array<uint8_t, 0> payload{};
    std::vector<uint8_t> response;
    if (!dev.sendAndReceive(m_featureIndex, FN_GET_LEVEL, payload, response))
        return -1;
    if (response.empty()) return -1;
    return static_cast<int>(response[0]);
}
