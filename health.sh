#!/bin/bash
# Quick health check — run anytime to see system status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OlbosQuant Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Read broker connection mode from .env if present
ENV_FILE="${ENV_FILE:-backend/.env}"
IBKR_CONN=$(grep -E "^IBKR_CONNECTION=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' | tr '[:upper:]' '[:lower:]')
IBKR_CONN="${IBKR_CONN:-clientportal}"

# Backend
if curl -s http://localhost:8000/api/market/broker > /dev/null 2>&1; then
  BROKER=$(curl -s http://localhost:8000/api/market/broker)
  STATUS=$(echo "$BROKER" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status'))" 2>/dev/null)
  MODE=$(echo "$BROKER" | python3 -c "import sys,json; d=json.load(sys.stdin); print('PAPER' if d.get('paper_mode') else 'LIVE')" 2>/dev/null)
  CONN=$(echo "$BROKER" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('connection_type','?'))" 2>/dev/null)
  echo "  Backend  ✅  running"
  echo "  Broker   $([ \"$STATUS\" = \"connected\" ] && echo '✅' || echo '❌')  $STATUS ($MODE, $CONN)"
else
  echo "  Backend  ❌  NOT running — run ./start.sh"
fi

# IBKR gateway reachability
if [ "$IBKR_CONN" = "clientportal" ] || [ "$IBKR_CONN" = "client_portal" ] || [ "$IBKR_CONN" = "cp" ]; then
  python3 -c "import socket; s=socket.socket(); s.settimeout(2); r=s.connect_ex(('127.0.0.1',5000)); s.close(); exit(r)" 2>/dev/null \
    && echo "  CP GW    ✅  reachable (port 5000)" \
    || echo "  CP GW    ❌  not reachable — start Client Portal Gateway & log in at https://localhost:5000"
else
  IBKR_PORT=$(grep -E "^IBKR_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
  IBKR_PORT="${IBKR_PORT:-4002}"
  python3 -c "import socket; s=socket.socket(); s.settimeout(2); r=s.connect_ex(('127.0.0.1',$IBKR_PORT)); s.close(); exit(r)" 2>/dev/null \
    && echo "  IB GW    ✅  connected (port $IBKR_PORT)" \
    || echo "  IB GW    ❌  not reachable — open IB Gateway/TWS on port $IBKR_PORT"
fi

# Prices
SPY=$(curl -s http://localhost:8000/api/market/snapshot/SPY 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"\${d.get('mid','?'):.2f} ({d.get('change_pct',0):+.2f}%)\")" 2>/dev/null)
echo "  SPY      📈  ${SPY:-unavailable}"

# Frontend
if curl -s http://localhost:3000 > /dev/null 2>&1; then
  echo "  UI       ✅  http://localhost:3000"
else
  echo "  UI       ❌  not running"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
