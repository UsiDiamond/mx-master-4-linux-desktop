#include "mx4hidpp/trigger.h"
#include "mx4hidpp/hidpp_device.h"

#include <array>
#include <vector>

// HID++ function nibbles for feature 0x1B04
static constexpr uint8_t FN_GET_COUNT          = 0x00;
static constexpr uint8_t FN_GET_CID_INFO       = 0x10;
static constexpr uint8_t FN_GET_CID_REPORTING  = 0x20;
static constexpr uint8_t FN_SET_CID_REPORTING  = 0x30;
static constexpr uint8_t FN_DIVERTED_BTN_EVENT = 0x00;  // notification function nibble

// ---------------------------------------------------------------------------

TriggerFeature::TriggerFeature(uint8_t featureIndex)
    : m_featureIndex(featureIndex)
{}

// ---------------------------------------------------------------------------

bool TriggerFeature::divertCid(HidppDevice& dev, uint16_t cid, bool diverted)
{
    // SetCidReporting payload (bytes):
    //   [0..1] CID (big-endian)
    //   [2]    flags byte:
    //            bit7=rawXY  bit6=persist  bit5=analytics  bit4=0
    //            bit3=0      bit2=0        bit1=divert     bit0=0
    //   [3..N] 0x00 padding
    //
    // We set persist=1 and divert=<diverted>; rawXY and analytics left clear.
    const uint8_t flags = (diverted ? 0x42u : 0x40u);  // bit6=persist, bit1=divert
    const std::array<uint8_t, 3> payload{
        static_cast<uint8_t>(cid >> 8),
        static_cast<uint8_t>(cid & 0xFF),
        flags
    };
    std::vector<uint8_t> response;
    return dev.sendAndReceive(m_featureIndex, FN_SET_CID_REPORTING, payload, response);
}

// ---------------------------------------------------------------------------

int16_t TriggerFeature::readDivertedCid(HidppDevice& dev, int timeoutMs)
{
    // Diverted button events arrive as HID++ notifications with:
    //   report[0]  = 0x11 (long)
    //   report[1]  = device index
    //   report[2]  = feature index (0x1B04's index on this device)
    //   report[3]  = (FN_DIVERTED_BTN_EVENT << 4) | sw-id  → high nibble 0x0
    //   report[4..5] = CID (big-endian, first diverted button)
    //   report[6..7] = CID of second simultaneous press (0x0000 if none)
    //
    // We poll readRaw and look for matching reports.
    std::vector<uint8_t> report;
    const int n = dev.readRaw(report, timeoutMs);
    if (n < 6) return -1;

    // Validate: long report, right device, right feature, notification function
    if (report[0] != 0x11)               return -1;
    if (report[1] != dev.deviceIndex())  return -1;
    if (report[2] != m_featureIndex)     return -1;
    if ((report[3] >> 4) != 0x00)        return -1;

    const uint16_t cid = static_cast<uint16_t>(
        (static_cast<uint16_t>(report[4]) << 8) | report[5]);
    return static_cast<int16_t>(cid);
}
