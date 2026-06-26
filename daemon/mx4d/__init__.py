"""mx4d — the standalone Linux daemon for the Logitech MX Master 4.

A dependency-light, raw-``hidraw`` HID++ 2.0 daemon that:

* fires the MX Master 4's native haptic motor (feature ``0x19B0``),
* captures the haptic "Actions Ring" touch panel as a software trigger by
  diverting it through REPROG CONTROLS V4 (feature ``0x1B04``),
* maps ambient desktop events — notifications, application focus changes and
  (best-effort) system sounds — to configurable haptic waveforms,
* exposes a small session D-Bus interface (``dev.usidiamond.mx4``) that drives
  the separate C++/Qt6 radial overlay (``mx4-radial``) — lazily launching it and
  calling ``Overlay.Show`` on an Actions-Ring press or a ``ShowMenu`` call.

It deliberately does **not** import Solaar / ``logitech_receiver``: it talks to
``/dev/hidraw*`` directly, exactly like ``tools/haptic_test.py``. No root is
required when the receiver node carries a session udev ACL.

Designed to run on both KDE Plasma 6 and LXQt; the haptics/HID core is fully
desktop-environment agnostic.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
