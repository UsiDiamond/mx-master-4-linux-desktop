#pragma once
#include <cstdint>
#include <optional>

class HidppDevice;

/// Resolves HID++ 2.0 feature numbers to their runtime feature indices.
///
/// HID++ 2.0 uses a per-device feature table.  Slot 0 (index 0x00) is always
/// the ROOT feature (0x0000), which exposes the GetFeature function (fn 0x10)
/// that maps feature numbers to indices.
///
/// Usage:
///   auto idx = FeatureIndex::resolve(dev, HapticsFeature::FEATURE_NUMBER);
///   if (!idx) { /* feature not supported on this device */ }
///   HapticsFeature haptics{*idx};
class FeatureIndex {
public:
    /// Resolve feature number @p featureNumber on @p dev.
    ///
    /// Sends GetFeature (ROOT feature 0x00, function 0x10) and returns the
    /// feature index byte, or std::nullopt if:
    ///   - the device doesn't support the feature
    ///   - the HID++ transaction failed
    ///
    /// @note This issues one HID++ round-trip per call.  Cache the result.
    [[nodiscard]] static std::optional<uint8_t>
    resolve(HidppDevice& dev, uint16_t featureNumber);
};
