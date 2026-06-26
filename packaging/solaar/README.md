# Solaar-first integration

This addon is **Solaar-first with a self-sufficient fallback**:

- **If you run Solaar** (the usual case — it already manages your MX Master 4), let
  Solaar own the *divert* of the Actions Ring panel. Once the **Haptic** control is
  diverted in Solaar, the firmware sends the panel's press/release over HID++, and the
  kernel broadcasts those notifications to **every** reader of the receiver's hidraw
  node — including our daemon. The daemon then times them itself and distinguishes a
  **tap** from a **press-and-hold** (each opens a ring). It also still provides the
  overlay, the haptics, and the ambient-event → haptic mapping. No device contention,
  and **no Solaar rule is required** — see below.
- **If you don't run Solaar**, the built-in daemon works entirely on its own (it diverts
  and captures the panel itself). Nothing here is required for that path — the standalone
  build never depends on Solaar.

So the two paths are independent: Solaar-first is purely additive.

> **Why no rule?** A Solaar *rule* fires once on the diverted key press and **cannot tell
> a tap from a hold**. The daemon reads the same diverted-key notifications directly and
> runs its own tap/hold timer, so it gives you both gestures. If you *also* install the
> legacy rule while the daemon is listening, the ring will open **twice** per tap.

> **Don't want to give up the panel's current behaviour?** You don't have to use the
> panel as the trigger at all. Bind the `mx4-show` helper to a hotkey or spare button
> instead (see [docs/INSTALL.md](../../docs/INSTALL.md) → "Triggering the ring") — the
> panel keeps doing whatever it does today, and the ring opens from your shortcut.

## How the trigger works under Solaar

```
  panel tap / hold
        │  Solaar diverts CID 0x01A0 "Haptic"  →  firmware emits divertedButtonsEvent
        ▼
  kernel broadcasts the HID++ notification to every hidraw reader
        │
        ▼
  mx4d daemon (passive listener)
        │  times press→release: tap (quick) vs. hold (≥ hold_threshold s)
        ▼
  Overlay.Show(tap_menu | hold_menu)  →  ring   (+ PlayHaptic on hover/commit)
```

Solaar owns only the *divert*; everything after it — tap/hold timing, the overlay, the
haptics — is the daemon. This is contention-free: diverted-key notifications are
broadcast, not consumed, so Solaar and the daemon both see them.

## Setup

Run the helper (idempotent; needs Solaar installed):

```bash
packaging/solaar/setup-solaar.sh
```

It will:
1. Divert the Actions Ring panel in Solaar: `solaar config '<device>' divert-keys Haptic Diverted`.
2. Set `trigger.divert_panel = false` in `~/.config/mx4desktop/config.ini` so the daemon
   leaves the divert to Solaar **unconditionally** (the explicit, forced Solaar-first
   path). Note `divert_panel = auto` (the default) already listens under a running Solaar,
   so this step only *pins* the behaviour.

That's it — with `mx4d` running, tap or hold the panel and the ring appears. **No Solaar
rule is needed** (and `setup-solaar.sh` no longer adds one by default).

> **Persistence / the Solaar CLI bug.** On some setups `solaar config … divert-keys`
> applies the divert to the device but then hits a Solaar marshalling bug
> (`Unable to marshal str as an array`) and exits before saving it — so the divert works
> *now* but does **not** survive a Solaar restart or the mouse sleeping/re-pairing. If
> that happens, set it once in the GUI instead — **Solaar → your MX Master 4 →
> Key/Button Diversion → Haptic → Diverted** — which persists it properly.

To **revert** to the self-sufficient standalone path:

```bash
packaging/solaar/setup-solaar.sh --revert   # un-diverts in Solaar, sets divert_panel = true
```

## Legacy: the Solaar rule (no-daemon use only)

You only need this if you want the ring to open **without** running `mx4d` (e.g. a Solaar
rule that calls `dbus-send` to whatever is listening). It fires once per press and
**cannot distinguish tap from hold**, and it will double-open the ring if the daemon is
also listening. The canonical YAML is in [`mx4-rules.yaml`](mx4-rules.yaml); add it via
Solaar's **Rule Editor** (Solaar → ☰ → Rule Editor) as a *Key* condition (`Haptic`,
`pressed`) with an *Execute* action running:

```
dbus-send --session --dest=dev.usidiamond.mx4 /dev/usidiamond/mx4 \
  dev.usidiamond.mx4.Daemon.ShowMenu string:default
```

`setup-solaar.sh --install-rule` appends it (with a backup), printing the double-fire
warning.

## Auto-detect (built in)

The daemon **auto-detects** a running Solaar so you never have to configure the coexist
behaviour by hand. `divert_panel = auto` (the default) scans `/proc` for a Solaar
background process at startup and, when found, does **not** divert the panel — it logs
that Solaar owns the divert and listens passively (to use the panel, divert the *Haptic*
control in Solaar, as above). When Solaar is **not** running it captures the panel itself
with confirmed HID++ writes, so the standalone path is fully self-sufficient and never
depends on Solaar (the detector never imports `logitech_receiver`). Transient
`solaar config` / `solaar show` CLI calls and the daemon's own process are excluded, so
only a real long-lived Solaar counts. The detection is decision-only — haptics are always
sent by the daemon directly.
