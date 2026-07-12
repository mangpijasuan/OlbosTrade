#!/bin/bash
# Quick health check — run anytime to see system status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OlbosTrade Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Backend
if curl -s http://localhost:8000/api/market/broker > /dev/null 2>&1; then
  BROKER=$(curl -s http://localhost:8000/api/market/broker)
  STATUS=$(echo "$BROKER" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status'))" 2>/dev/null)
  MODE=$(echo "$BROKER" | python3 -c "import sys,json; d=json.load(sys.stdin); print('PAPER' if d.get('paper_mode') else 'LIVE')" 2>/dev/null)
  echo "  Backend  ✅  running"
  echo "  Broker   ✅  $STATUS ($MODE)"
else
  echo "  Backend  ❌  NOT running — run ./start.sh"
fi

# IB Gateway
python3 -c "import socket; s=socket.socket(); s.settimeout(2); r=s.connect_ex(('127.0.0.1',4002)); s.close(); exit(r)" 2>/dev/null \
  && echo "  IB GW    ✅  connected (port 4002)" \
  || echo "  IB GW    ❌  not reachable — open IB Gateway"

# Prices
SPY=$(curl -s http://localhost:8000/api/market/snapshot/SPY 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"\${d.get('mid','?'):.2f} ({d.get('change_pct',0):+.2f}%)\")" 2>/dev/null)
echo "  SPY      📈  \$$SPY"

# Frontend
if curl -s http://localhost:3000 > /dev/null 2>&1; then
  echo "  UI       ✅  http://localhost:3000"
else
  echo "  UI       ❌  not running"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
