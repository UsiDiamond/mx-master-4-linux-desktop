# Solaar-first integration

This addon is **Solaar-first with a self-sufficient fallback**:

- **If you run Solaar** (the usual case — it already manages your MX Master 4), let
  Solaar own the device and the Actions Ring trigger. Solaar diverts the haptic panel
  and a Solaar **rule** fires the overlay. Our daemon then does **not** touch the panel
  (it runs with `trigger.divert_panel = false`) and only provides the overlay, the
  haptics, and the ambient-event → haptic mapping over D-Bus. No device contention.
- **If you don't run Solaar**, the built-in daemon works entirely on its own (it diverts
  and captures the panel itself). Nothing here is required for that path — the standalone
  build never depends on Solaar.

So the two paths are independent: Solaar-first is purely additive.

## How the trigger works under Solaar

```
  panel tap ──▶ Solaar (diverts CID 0x01A0 "Haptic") ──▶ Solaar rule
                                                            │ Execute
                                                            ▼
        dbus-send … dev.usidiamond.mx4.Daemon.ShowMenu "default"
                                                            │
                                                            ▼
                          mx4d daemon ──▶ Overlay.Show(default)  ──▶ ring
                              └── plays haptics (PlayHaptic) on hover/commit
```

The daemon still owns haptics and ambient events; only the *trigger* is delegated to
Solaar. This is the supported, contention-free Solaar path (rules fire on diverted-key
HID++ notifications).

## Setup

Run the helper (idempotent; needs Solaar installed):

```bash
packaging/solaar/setup-solaar.sh
```

It will:
1. Divert the Actions Ring panel in Solaar: `solaar config '<device>' divert-keys Haptic Diverted`.
2. Set `trigger.divert_panel = false` in `~/.config/mx4desktop/config.ini` so the daemon
   leaves the panel to Solaar.
3. Offer to add the rule below to `~/.config/solaar/rules.yaml` (with a backup first), or
   tell you how to add it via Solaar's GUI rule editor.

To **revert** to the self-sufficient standalone path:

```bash
packaging/solaar/setup-solaar.sh --revert   # un-diverts in Solaar, sets divert_panel = true
```

## The Solaar rule

Condition **Key = `Haptic`, pressed** → action **Execute** `dbus-send … ShowMenu`. The
canonical YAML is in [`mx4-rules.yaml`](mx4-rules.yaml). The safest way to add it is
through Solaar's **Rule Editor** (Solaar → ☰ → Rule Editor): add a rule with a *Key*
condition (`Haptic`, `pressed`) and an *Execute* action running:

```
dbus-send --session --dest=dev.usidiamond.mx4 /dev/usidiamond/mx4 \
  dev.usidiamond.mx4.Daemon.ShowMenu string:default
```

> The physical-tap path still needs a real tap to confirm end-to-end (we can't press the
> panel from software). The `divert-keys` write and the `ShowMenu` D-Bus call are both
> verified; the Solaar rule firing on the tap is the last manual check.

## Coming next (auto-detect polish)

A follow-up makes the daemon **auto-detect** a running Solaar and flip `divert_panel`
itself (so no manual config), and optionally route haptics through Solaar's
`feature_request` when Solaar holds the device. Until then, this opt-in setup is the
Solaar-first path, and the standalone default keeps working untouched.
