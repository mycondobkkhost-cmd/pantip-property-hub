#!/usr/bin/env bash
# Create or redeploy Property Hub on Render (needs RENDER_API_KEY in env or .env).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${RENDER_API_KEY:?Set RENDER_API_KEY (Render Dashboard → Account → API Keys)}"

SERVICE_ID="${RENDER_SERVICE_ID:-}"

if [[ -z "$SERVICE_ID" ]]; then
  echo "RENDER_SERVICE_ID not set — listing services..."
  curl -sf "https://api.render.com/v1/services?limit=20" \
    -H "Authorization: Bearer $RENDER_API_KEY" | python3 - <<'PY'
import json, sys
data = json.load(sys.stdin)
for item in data:
    s = item.get("service") or item
    name = s.get("name", "")
    sid = s.get("id", "")
    url = (s.get("serviceDetails") or {}).get("url") or s.get("url") or ""
    if "property-hub" in name.lower() or "pantip" in name.lower():
        print(f"{sid}\t{name}\t{url}")
PY
  echo ""
  echo "If empty, create once via Blueprint:"
  echo "  https://dashboard.render.com/blueprint/new?repo=https://github.com/mycondobkkhost-cmd/pantip-property-hub"
  exit 1
fi

echo "Triggering deploy for $SERVICE_ID ..."
curl -sf -X POST "https://api.render.com/v1/services/${SERVICE_ID}/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"clearCache":"do_not_clear"}' | python3 -m json.tool

echo "Done. Check https://dashboard.render.com"
