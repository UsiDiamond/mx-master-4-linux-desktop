#pragma once
#include <cstdint>
#include <span>
#include <string>
#include <vector>

// Forward-declare the opaque hidapi handle so callers don't need hidapi headers.
struct hid_device_;

/// Thin RAII wrapper around a single HID++ 2.0 device opened via hidapi.
///
/// All communication goes through sendAndReceive() which:
///   1. Builds a 20-byte long HID++ report (report id 0x11).
///   2. Writes it to the hidraw node.
///   3. Reads back the matching response (same featureIndex + function nibble).
///
/// Error handling: methods return bool; no exceptions are thrown from hidapi paths.
class HidppDevice {
public:
    /// @param path        Path to the hidraw node, e.g. "/dev/hidraw11"
    /// @param deviceIndex HID++ device index (1 = receiver itself; 2 = first paired device)
    explicit HidppDevice(const std::string& path, uint8_t deviceIndex = 2);
    ~HidppDevice();

    // Non-copyable, movable
    HidppDevice(const HidppDevice&) = delete;
    HidppDevice& operator=(const HidppDevice&) = delete;
    HidppDevice(HidppDevice&&) noexcept;
    HidppDevice& operator=(HidppDevice&&) noexcept;

    /// Open the hidraw node.  Returns false on permission error or missing path.
    [[nodiscard]] bool open();

    /// Close the hidraw node (safe to call on an already-closed device).
    void close();

    /// Returns true if the device is currently open.
    [[nodiscard]] bool isOpen() const noexcept { return m_dev != nullptr; }

    /// Send a HID++ 2.0 long report and read back the response.
    ///
    /// @param featureIndex  Feature index byte (resolved at runtime via FeatureIndex)
    /// @param function      Function nibble (bits 7-4 of byte 3; bits 3-0 = software id 0xE)
    /// @param payload       Up to 13 bytes of request payload (zero-padded to fill the report)
    /// @param response      Filled with the 17 bytes of payload from the response report
    /// @return true on success
    [[nodiscard]] bool sendAndReceive(uint8_t featureIndex,
                                      uint8_t function,
                                      std::span<const uint8_t> payload,
                                      std::vector<uint8_t>& response);

    /// Blocking read of the next HID++ report (any featureIndex).
    /// Useful for divert-event capture in the trigger polling loop.
    ///
    /// @param report   Filled with up to 20 raw bytes
    /// @param timeoutMs  Timeout in milliseconds; -1 = block indefinitely
    /// @return number of bytes read, or -1 on error/timeout
    [[nodiscard]] int readRaw(std::vector<uint8_t>& report, int timeoutMs = 500);

    [[nodiscard]] uint8_t deviceIndex() const noexcept { return m_deviceIndex; }
    [[nodiscard]] const std::string& path() const noexcept { return m_path; }

private:
    std::string m_path;
    uint8_t m_deviceIndex;
    hid_device_* m_dev{nullptr};
};
