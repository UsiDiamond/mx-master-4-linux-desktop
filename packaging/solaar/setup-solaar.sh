#!/usr/bin/env bash
# Solaar-first setup for mx-master-4-desktop.
#
# Default: let Solaar own the Actions Ring divert (divert the Haptic panel + tell the
# daemon to stop diverting it), so the two never fight over the device. The standalone
# path is unaffected and remains the default until you run this.
#
# With the daemon (mx4d) running you do NOT need a Solaar rule: once the Haptic panel is
# diverted, the daemon hears the key directly and distinguishes a tap from a press-and-
# hold (a Solaar rule cannot, and would fire the ring a second time). The rule path is
# kept only as a legacy way to open the ring when the daemon is not running.
#
#   setup-solaar.sh                 # Solaar-first (divert Haptic + set config; no rule)
#   setup-solaar.sh --install-rule  # LEGACY: also append the Solaar rule (no-daemon use)
#   setup-solaar.sh --revert        # back to the self-sufficient standalone path
#
# Idempotent and non-destructive (backs up before touching rules.yaml).
set -euo pipefail

DEVICE="${MX4_DEVICE_NAME:-MX Master 4}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/mx4desktop/config.ini"
SOLAAR_RULES="${XDG_CONFIG_HOME:-$HOME/.config}/solaar/rules.yaml"
RULE_SRC="$(cd "$(dirname "$0")" && pwd)/mx4-rules.yaml"
REVERT=0; INSTALL_RULE=0
for a in "$@"; do case "$a" in
  --revert) REVERT=1;;
  --install-rule) INSTALL_RULE=1;;
  -h|--help) sed -n '2,17p' "$0"; exit 0;;
  *) echo "unknown arg: $a" >&2; exit 2;;
esac; done

command -v solaar >/dev/null || { echo "error: solaar is not installed (this is the Solaar-first path)"; exit 1; }

# Set a key in the [trigger] section of our INI without disturbing other keys.
set_divert_panel() {  # $1 = true|false
  python3 - "$CONFIG" "$1" <<'PY'
import configparser, os, sys
path, val = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
cp = configparser.ConfigParser(); cp.optionxform = str
cp.read(path)
if not cp.has_section('trigger'): cp.add_section('trigger')
cp.set('trigger', 'divert_panel', val)
with open(path, 'w') as f: cp.write(f)
print(f"  set [trigger] divert_panel = {val} in {path}")
PY
}

if [ "$REVERT" = 1 ]; then
  echo "==> Reverting to the standalone (self-sufficient) path"
  solaar config "$DEVICE" divert-keys Haptic Regular 2>/dev/null \
    || echo "  ! could not un-divert via the Solaar CLI (marshalling bug); set Haptic = Regular in Solaar's UI."
  set_divert_panel true
  echo "  NOTE: remove the mx4 'Haptic -> ShowMenu' rule from Solaar's Rule Editor if you added it."
  echo "Done. The built-in daemon will divert + capture the panel itself again."
  exit 0
fi

echo "==> Enabling Solaar-first trigger for '$DEVICE'"
echo "--> diverting the Actions Ring panel in Solaar (Haptic = Diverted)"
if ! solaar config "$DEVICE" divert-keys Haptic Diverted 2>/dev/null; then
  echo "  ! 'solaar config divert-keys' failed (a known Solaar CLI marshalling bug:"
  echo "    \"Unable to marshal str as an array\"). Set it by hand in Solaar's UI instead:"
  echo "    open Solaar -> your MX Master 4 -> Key/Button Diversion -> Haptic = Diverted."
fi

echo "--> telling the daemon NOT to divert the panel (Solaar owns it now)"
set_divert_panel false

if [ "$INSTALL_RULE" = 1 ]; then
  echo
  echo "  NOTE: a Solaar rule is NO LONGER NEEDED. With mx4d running, the daemon hears the"
  echo "  diverted Haptic key directly and tells a tap from a hold (a rule cannot). If the"
  echo "  daemon is also listening, this rule will open the ring a SECOND time on each tap."
  echo "  Only keep it if you run WITHOUT mx4d."
  if [ -f "$SOLAAR_RULES" ] && grep -q "dev.usidiamond.mx4.Daemon.ShowMenu" "$SOLAAR_RULES"; then
    echo "--> Solaar rule already present, leaving rules.yaml untouched"
  else
    mkdir -p "$(dirname "$SOLAAR_RULES")"
    [ -f "$SOLAAR_RULES" ] && cp -a "$SOLAAR_RULES" "$SOLAAR_RULES.mx4.bak" && echo "--> backed up rules.yaml -> $SOLAAR_RULES.mx4.bak"
    # Append just the rule body (skip the YAML header lines from the reference file).
    grep -vE '^%YAML|^---|^\.\.\.|^#' "$RULE_SRC" >> "$SOLAAR_RULES"
    echo "--> appended the mx4 rule to $SOLAAR_RULES (review it in Solaar's Rule Editor)"
  fi
else
  echo
  echo "No Solaar rule needed: with the daemon (mx4d) running, it hears the diverted Haptic"
  echo "key directly and gives you tap (quick press) vs. hold (>= hold_threshold s), each"
  echo "opening a ring. Just confirm the Haptic divert above stuck (check Solaar's UI) and"
  echo "tap the panel. (Legacy no-daemon path: re-run with --install-rule; it cannot tell a"
  echo "tap from a hold.)"
fi

echo
echo "Done. With the daemon running (mx4d), a tap OR a hold of the haptic panel opens the ring."
echo "If the divert does not survive a Solaar restart, set Haptic = Diverted ONCE in Solaar's"
echo "UI (the CLI write can hit a Solaar marshalling bug that applies it but skips saving it)."
echo "Revert anytime with:  $(basename "$0") --revert"
