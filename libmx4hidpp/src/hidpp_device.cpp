#include "mx4hidpp/hidpp_device.h"

#include <hidapi/hidapi.h>

#include <algorithm>
#include <cstring>

// Software-ID nibble: 0xE (arbitrary; identifies our writes vs. other software)
static constexpr uint8_t SW_ID = 0x0E;

// HID++ report IDs
static constexpr uint8_t REPORT_LONG  = 0x11;  // 20-byte report
static constexpr uint8_t REPORT_SHORT = 0x10;  // 7-byte report (rarely used here)

static constexpr int REPORT_LONG_LEN = 20;

// ---------------------------------------------------------------------------

HidppDevice::HidppDevice(const std::string& path, uint8_t deviceIndex)
    : m_path(path), m_deviceIndex(deviceIndex)
{
    // hidapi library init is idempotent (ref-counted internally)
    hid_init();
}

HidppDevice::~HidppDevice()
{
    close();
}

HidppDevice::HidppDevice(HidppDevice&& other) noexcept
    : m_path(std::move(other.m_path))
    , m_deviceIndex(other.m_deviceIndex)
    , m_dev(other.m_dev)
{
    other.m_dev = nullptr;
}

HidppDevice& HidppDevice::operator=(HidppDevice&& other) noexcept
{
    if (this != &other) {
        close();
        m_path        = std::move(other.m_path);
        m_deviceIndex = other.m_deviceIndex;
        m_dev         = other.m_dev;
        other.m_dev   = nullptr;
    }
    return *this;
}

// ---------------------------------------------------------------------------

bool HidppDevice::open()
{
    if (m_dev) return true;  // already open

    // hidapi open-path works with hidraw paths directly on Linux
    m_dev = hid_open_path(m_path.c_str());
    return m_dev != nullptr;
}

void HidppDevice::close()
{
    if (m_dev) {
        hid_close(m_dev);
        m_dev = nullptr;
    }
}

// ---------------------------------------------------------------------------

bool HidppDevice::sendAndReceive(uint8_t featureIndex,
                                  uint8_t function,
                                  std::span<const uint8_t> payload,
                                  std::vector<uint8_t>& response)
{
    if (!m_dev) return false;

    // Build the 20-byte long HID++ 2.0 request report.
    // Layout:
    //   [0]  report id  = 0x11
    //   [1]  device idx = m_deviceIndex
    //   [2]  feature idx
    //   [3]  (function << 4) | SW_ID
    //   [4..19] payload (zero-padded)
    std::array<uint8_t, REPORT_LONG_LEN> report{};
    report[0] = REPORT_LONG;
    report[1] = m_deviceIndex;
    report[2] = featureIndex;
    report[3] = static_cast<uint8_t>((function << 4) | SW_ID);

    const std::size_t payloadLen = std::min(payload.size(), std::size_t{16});
    std::copy_n(payload.begin(), payloadLen, report.begin() + 4);

    // hid_write prepends a 0x00 byte on Linux (report number already embedded)
    if (hid_write(m_dev, report.data(), report.size()) < 0)
        return false;

    // Read back; retry on stray reports (different feature/function)
    for (int tries = 0; tries < 8; ++tries) {
        std::array<uint8_t, REPORT_LONG_LEN> resp{};
        const int n = hid_read_timeout(m_dev, resp.data(), resp.size(), 1000);
        if (n < 4) return false;

        // Match on report id, device index, feature index, and function nibble
        if (resp[0] == REPORT_LONG
            && resp[1] == m_deviceIndex
            && resp[2] == featureIndex
            && (resp[3] >> 4) == function)
        {
            response.assign(resp.begin() + 4, resp.begin() + n);
            return true;
        }
        // HID++ error report (feature 0xFF)
        if (resp[2] == 0xFF) return false;
    }
    return false;
}

// ---------------------------------------------------------------------------

int HidppDevice::readRaw(std::vector<uint8_t>& report, int timeoutMs)
{
    if (!m_dev) return -1;

    report.resize(REPORT_LONG_LEN);
    const int n = hid_read_timeout(m_dev,
                                   report.data(),
                                   report.size(),
                                   timeoutMs);
    if (n > 0) report.resize(static_cast<std::size_t>(n));
    return n;
}
