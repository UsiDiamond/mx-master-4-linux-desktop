#include "mx4hidpp/feature_index.h"
#include "mx4hidpp/hidpp_device.h"

#include <array>
#include <vector>

// ROOT feature is always at index 0x00.
// GetFeature function is 0x10 (nibble), payload = [featureNumber hi, featureNumber lo, 0x00]
static constexpr uint8_t ROOT_FEATURE_INDEX = 0x00;
static constexpr uint8_t GET_FEATURE_FN     = 0x10;

std::optional<uint8_t>
FeatureIndex::resolve(HidppDevice& dev, uint16_t featureNumber)
{
    if (!dev.isOpen()) return std::nullopt;

    // Payload: 2 bytes of feature number, 1 byte obsolete sw-id
    const std::array<uint8_t, 3> payload{
        static_cast<uint8_t>(featureNumber >> 8),
        static_cast<uint8_t>(featureNumber & 0xFF),
        0x00
    };

    std::vector<uint8_t> response;
    if (!dev.sendAndReceive(ROOT_FEATURE_INDEX, GET_FEATURE_FN, payload, response))
        return std::nullopt;

    // Response payload[0] = feature index (0x00 means not supported)
    if (response.empty() || response[0] == 0x00)
        return std::nullopt;

    return response[0];
}
