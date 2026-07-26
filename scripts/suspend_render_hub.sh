#!/usr/bin/env bash
# Suspend (do not delete) Render property-hub after Fly/DNS cutover.
# Ask before destructive delete — this script only suspends.
set -euo pipefail

SID="${RENDER_SERVICE_ID:-srv-d99pvk67r5hc73bll3o0}"
CFG="${HOME}/.render/cli.yaml"
KEY="$(python3 -c "import re,pathlib; t=pathlib.Path('$CFG').read_text(); print(re.search(r'key:\\s*(\\S+)', t).group(1))")"

echo "Suspending Render service $SID (property-hub)…"
curl -sS -X POST "https://api.render.com/v1/services/${SID}/suspend" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Accept: application/json" | python3 -m json.tool | head -40

echo ""
echo "Admins: use https://hub.realxtateth.com only (not *.onrender.com)."
echo "To resume later: POST /v1/services/${SID}/resume"
echo "Do NOT delete the service until Fly has been stable for a few days."
