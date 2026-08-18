#!/usr/bin/env bash
#
# Keep the gateway running by itself (macOS).
#
# The gateway has to be up for anything to reach WhatsApp: it holds the socket,
# it is the only thing that can produce a pairing QR, and messages posted while
# it is down are simply missed -- it reads live traffic, not history. Started by
# hand in a terminal it dies with the terminal, and the CRM then shows "gateway
# not responding" with no clue that a window got closed hours ago.
#
# This registers it as a LaunchAgent: starts at login, restarts if it crashes,
# survives closing the terminal.
#
#   ./install-autostart.sh            install and start
#   ./install-autostart.sh --uninstall  stop and remove
#
# Not a substitute for hosting it somewhere always-on. It runs while this Mac is
# awake and online, and stops when the Mac does.

set -euo pipefail

LABEL="com.balaji.crm.gateway"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HERE/gateway.log"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed. The gateway will not start again on its own."
  exit 0
fi

NODE="$(command -v node || true)"
if [ -z "$NODE" ]; then
  echo "node is not on PATH. Install Node 22+ and re-run." >&2
  exit 1
fi
if [ ! -f "$HERE/.env" ]; then
  echo "No $HERE/.env — copy .env.example and fill it in first." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# `node --env-file-if-exists=.env src/index.js` is what `npm start` runs. Calling
# node directly avoids depending on npm being on launchd's very short PATH.
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NODE</string>
    <string>--env-file-if-exists=.env</string>
    <string>src/index.js</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>RunAtLoad</key><true/>
  <!-- Restart if it exits for any reason: a dropped WhatsApp socket, an OOM,
       a crash. The gateway is designed to be restartable -- the session is on
       disk and undelivered messages are journalled. -->
  <key>KeepAlive</key><true/>
  <!-- Do not hammer WhatsApp if it is failing to start in a loop. -->
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLISTEOF

plutil -lint "$PLIST" >/dev/null

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed. The gateway now starts at login and restarts if it stops."
echo
echo "  logs:    tail -f $LOG"
echo "  status:  launchctl print gui/$(id -u)/$LABEL | grep -E 'state|pid'"
echo "  stop:    ./install-autostart.sh --uninstall"
