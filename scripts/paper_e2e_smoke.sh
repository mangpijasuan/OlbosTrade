#!/usr/bin/env bash
# Local / staging smoke — does NOT place orders.
# Usage: BASE_URL=http://127.0.0.1:8000 bash scripts/paper_e2e_smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${API_KEY:-}"

hdr=(-H "Accept: application/json")
if [[ -n "$API_KEY" ]]; then
  hdr+=(-H "X-Api-Key: $API_KEY")
fi

echo "Smoke against $BASE_URL"
echo "── health ──"
curl -fsS "${hdr[@]}" "$BASE_URL/api/health" | head -c 400 || curl -fsS "${hdr[@]}" "$BASE_URL/health" | head -c 400
echo ""
echo "── execution mode ──"
curl -fsS "${hdr[@]}" "$BASE_URL/api/trade-desk/execution-mode"
echo ""
echo "── kill switch ──"
curl -fsS "${hdr[@]}" "$BASE_URL/api/trade-desk/kill-switch"
echo ""
echo "── pending ──"
curl -fsS "${hdr[@]}" "$BASE_URL/api/trade-desk/pending"
echo ""
echo "── evaluate-equity (advisory) ──"
curl -fsS "${hdr[@]}" -X POST "$BASE_URL/api/trade-desk/evaluate-equity" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","action":"BUY","shares":1,"entry_price":150,"stop_price":145,"order_type":"limit"}'
echo ""
echo "OK — read-only smoke finished (no orders placed)"
