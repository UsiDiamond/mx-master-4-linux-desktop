#pragma once
#include <cstdint>

class HidppDevice;

/// Driver for HID++ feature 0x1B04 — SPECIAL KEYS AND MOUSE BUTTONS.
///
/// This feature allows the host to "divert" button events so that they are
/// reported via HID++ notifications (report id 0x11, feature index bytes)
/// instead of being sent as standard HID mouse/keyboard reports.
///
/// We use it to capture the Actions Ring press (Haptic control, CID TBD —
/// likely 0x0109 or similar; confirm with: solaar -dd 2>&1 | grep divert).
///
/// Flow:
///   1. TriggerFeature::divertCid(dev, cid, true)   — reroute button events
///   2. Loop: TriggerFeature::readDivertedCid(dev)   — blocking poll for press
///   3. On daemon exit: divertCid(dev, cid, false)   — restore normal behaviour
class TriggerFeature {
public:
    static constexpr uint16_t FEATURE_NUMBER = 0x1B04;

    // Well-known CID constants (update after hardware confirmation)
    // MX Master 4 Actions Ring — exact CID to be confirmed from HW; placeholder 0x0109
    static constexpr uint16_t CID_ACTIONS_RING = 0x0109;

    /// @param featureIndex  Runtime index resolved via FeatureIndex::resolve()
    explicit TriggerFeature(uint8_t featureIndex);

    /// Divert (or un-divert) a control ID so its events arrive as HID++ reports.
    ///
    /// Sends SetCidReporting (fn 0x30) with the raw/divert/persist flags.
    ///
    /// @param dev       Open HidppDevice
    /// @param cid       Control ID to divert (e.g. CID_ACTIONS_RING)
    /// @param diverted  true = divert, false = restore to regular HID
    /// @return true on success
    [[nodiscard]] bool divertCid(HidppDevice& dev, uint16_t cid, bool diverted);

    /// Block until a diverted CID event arrives, or the timeout elapses.
    ///
    /// Reads raw HID++ reports from the device looking for a DivertedButtonsEvent
    /// (fn 0x00 notification carrying the pressed CID).
    ///
    /// @param dev        Open HidppDevice
    /// @param timeoutMs  Milliseconds to wait; 0 = non-blocking; -1 = block forever
    /// @return CID of the pressed button, or -1 on timeout/error
    [[nodiscard]] int16_t readDivertedCid(HidppDevice& dev, int timeoutMs = 500);

private:
    uint8_t m_featureIndex;
};
