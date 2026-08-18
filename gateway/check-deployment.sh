#!/usr/bin/env bash
#
# Why is there no QR on the deployed app?
#
# Three things have to line up, and all three fail the same way on screen —
# "the gateway is not running", with no code. This says which one it is.
#
#   ./check-deployment.sh https://your-api.onrender.com
#
# Reads no secrets and sends none: every probe below is an unauthenticated
# request, and it is the *shape* of the refusal that identifies the problem.

set -u

API="${1:-}"
if [ -z "$API" ]; then
  echo "usage: $0 https://your-api.onrender.com"
  exit 64
fi
API="${API%/}"

code() { curl -s -m 45 -o /dev/null -w "%{http_code}" "$@" 2>/dev/null || echo "000"; }
body() { curl -s -m 45 "$@" 2>/dev/null; }

echo
echo "Checking $API"
echo "(a sleeping free-tier service takes ~60s to answer the first request)"
echo

# ---------------------------------------------------------------------------
echo "1. Is the API awake?"
health=$(code "$API/health")
case "$health" in
  200) echo "   OK — answered 200." ;;
  000) echo "   FAILED — no response. Wrong URL, or the service is down."; exit 1 ;;
  *)   echo "   FAILED — answered $health rather than 200."; exit 1 ;;
esac

# ---------------------------------------------------------------------------
echo
echo "2. Is the pairing code deployed?"
# 401 = the route exists and wants a login, which is the right answer here.
# 404 = this build predates the Connect button.
pair=$(code -X POST "$API/whatsapp/pair")
case "$pair" in
  401|403) echo "   OK — /whatsapp/pair exists (refused an anonymous caller: $pair)." ;;
  404) echo "   PROBLEM — /whatsapp/pair is 404, so Render is running an older build."
       echo "   Fix: Render → your API service → Manual Deploy → Deploy latest commit."
       echo "        The start command runs 'alembic upgrade head', which adds the"
       echo "        columns this needs." ;;
  *)   echo "   UNEXPECTED — $pair. Check the service log." ;;
esac

# ---------------------------------------------------------------------------
echo
echo "3. Does the API have a gateway secret configured?"
# Unsigned on purpose. 403 "Missing gateway signature" means the endpoint is
# live and checking. 503 "ingest_disabled" means WHATSAPP_INGEST_SECRET is
# unset, so the API rejects the gateway no matter what it sends.
cmd_body=$(body "$API/internal/whatsapp/commands")
cmd_code=$(code "$API/internal/whatsapp/commands")
case "$cmd_code" in
  403) echo "   OK — the gateway endpoint is live and demanding a signature." ;;
  503) echo "   PROBLEM — WHATSAPP_INGEST_SECRET is not set on Render."
       echo "   Every gateway request is refused with 503, so no QR can ever arrive."
       echo "   Fix: Render → your API service → Environment → add"
       echo "        WHATSAPP_INGEST_SECRET, then put the SAME value in gateway/.env." ;;
  404) echo "   PROBLEM — endpoint missing; same stale build as step 2." ;;
  *)   echo "   UNEXPECTED — $cmd_code: $cmd_body" ;;
esac

# ---------------------------------------------------------------------------
echo
echo "4. Where is this gateway configured to report?"
configured=$(grep -E "^API_BASE_URL=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
if [ -z "$configured" ]; then
  echo "   API_BASE_URL is not set in gateway/.env — it defaults to"
  echo "   http://127.0.0.1:8000, i.e. this machine, NOT $API."
  echo "   Fix: add  API_BASE_URL=$API  to gateway/.env and restart the gateway."
elif [ "${configured%/}" = "$API" ]; then
  echo "   OK — pointed at $API."
else
  echo "   PROBLEM — pointed at: $configured"
  echo "   That is not $API, so its QR is being delivered somewhere else."
  echo "   Fix: set  API_BASE_URL=$API  in gateway/.env and restart the gateway."
fi

echo
echo "Reminder: the QR is produced by the gateway, not by the website. Whatever"
echo "the checks above say, 'npm start' has to be running somewhere for a code"
echo "to appear — and the secret in gateway/.env must match the one on Render."
echo
