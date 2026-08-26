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

# Outside the repo, deliberately. launchd opens these paths itself, before the
# job starts and without the job's privileges -- so a log inside a folder macOS
# protects makes the whole job fail to spawn with EX_CONFIG (78), which reads
# like a broken plist and is not one.
LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/balaji-gateway.log"
mkdir -p "$LOG_DIR"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed. The gateway will not start again on its own."
  exit 0
fi

# macOS will not let a LaunchAgent into Desktop, Documents or Downloads.
#
# Not a permissions setting this script can fix, and not one the failure
# explains: launchd starts the job, node cannot even resolve its own working
# directory, and it dies with `EPERM: operation not permitted, uv_cwd` in a log
# most people never find. It then retries every 30 seconds, for ever.
#
# So refuse up front and say what actually fixes it, rather than installing
# something that cannot work.
case "$HERE/" in
  "$HOME"/Downloads/*|"$HOME"/Desktop/*|"$HOME"/Documents/*)
    protected="${HERE#$HOME/}"; protected="${protected%%/*}"
    cat >&2 <<EOSTOP
This checkout is in ~/$protected, and macOS does not let a background service
read Desktop, Documents or Downloads. launchd would start the gateway and node
would die immediately with:

    Error: EPERM: operation not permitted, uv_cwd

Two ways out, in order of preference:

  1. Move the checkout somewhere unprotected, then re-run this:

       mv "$(dirname "$HERE")" ~/Balaji_CRM
       cd ~/Balaji_CRM/gateway && ./install-autostart.sh

  2. Grant Full Disk Access to node in System Settings -> Privacy & Security.
     This works, but it is a broad permission to hand a runtime, and it has to
     be re-granted whenever node is upgraded.

Until then the gateway still runs perfectly when started by hand:

    cd "$HERE" && npm start

EOSTOP
    exit 1 ;;
esac

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

# Check it actually came up, rather than reporting success on faith.
#
# This used to print "Installed. The gateway now starts at login" the instant
# bootstrap returned -- which it does whether or not the job can run. A job
# that dies on every spawn looks exactly like a healthy one from here, and the
# CRM then says "gateway not responding" while this script says it is fine.
printf 'Waiting for it to start'
for _ in $(seq 1 20); do
  if pgrep -qf "$HERE/src/index.js" || grep -aq "connected to WhatsApp" "$LOG" 2>/dev/null; then
    started=1
    break
  fi
  printf '.'
  sleep 1
done
echo

if [ -z "${started:-}" ]; then
  echo "FAILED — the job was installed but nothing is running." >&2
  echo >&2
  echo "Last exit code:" >&2
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "last exit" >&2 || true
  echo >&2
  echo "Log ($LOG):" >&2
  tail -n 15 "$LOG" >&2 2>/dev/null || echo "  (empty)" >&2
  echo >&2
  echo "Remove it with: ./install-autostart.sh --uninstall" >&2
  exit 1
fi

echo "Installed and running. It starts at login and restarts if it stops."
echo
echo "  logs:    tail -f $LOG"
echo "  status:  launchctl print gui/$(id -u)/$LABEL | grep -E 'state|pid'"
echo "  stop:    ./install-autostart.sh --uninstall"
