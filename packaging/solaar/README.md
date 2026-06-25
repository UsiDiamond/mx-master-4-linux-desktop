# Solaar-first integration

This addon is **Solaar-first with a self-sufficient fallback**:

- **If you run Solaar** (the usual case — it already manages your MX Master 4), let
  Solaar own the device and the Actions Ring trigger. Solaar diverts the haptic panel
  and a Solaar **rule** fires the overlay. Our daemon then does **not** touch the panel
  and only provides the overlay, the haptics, and the ambient-event → haptic mapping over
  D-Bus. No device contention.

  **This is now automatic.** `trigger.divert_panel` defaults to **`auto`**: on startup the
  daemon detects a running Solaar background process and, if present, defers the trigger to
  Solaar (never diverting the panel) — no manual config needed. You still need the Solaar
  **rule** that turns the diverted Haptic key into `ShowMenu`; `setup-solaar.sh` installs it
  (or add it in Solaar's Rule Editor). `auto` falls back to standalone capture the moment
  Solaar is not running, so you always have a working trigger.
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
   leaves the panel to Solaar **unconditionally** (the explicit, forced Solaar-first path).
3. Offer to add the rule below to `~/.config/solaar/rules.yaml` (with a backup first), or
   tell you how to add it via Solaar's GUI rule editor.

> Since `divert_panel` now defaults to **`auto`** (auto-defer to a running Solaar), step 2 is
> no longer strictly required to avoid contention — but `setup-solaar.sh` is still the easy way
> to **install the Solaar rule** and to *pin* the forced Solaar-first behaviour. The rule is
> what actually fires the overlay on a tap, so run it (or add the rule by hand) at least once.

To **revert** to the self-sufficient standalone path:

```bash
packaging/solaar/setup-solaar.sh --revert   # un-diverts in Solaar, sets divert_panel = true
```

(If you prefer the hands-off behaviour, set `divert_panel = auto` and just keep the Solaar
rule installed: the daemon captures standalone when Solaar is down and defers when it is up.)

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

## Auto-detect (now built in)

The daemon **auto-detects** a running Solaar and defers the trigger to it without any
manual config: `divert_panel = auto` (the default) scans `/proc` for a Solaar background
process at startup and, when found, never diverts the panel (logging
`Solaar detected -> deferring the Actions Ring trigger to Solaar`). When Solaar is not
running it captures the panel itself, so the standalone path is fully self-sufficient and
never depends on Solaar (the detector never imports `logitech_receiver`). Transient
`solaar config` / `solaar show` CLI calls and the daemon's own process are excluded, so only
a real long-lived Solaar counts. The detection is decision-only — haptics are still sent by
the daemon directly; routing haptics through Solaar's `feature_request` remains a possible
future option.
