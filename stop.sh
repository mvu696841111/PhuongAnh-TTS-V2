#!/bin/bash
# ===========================================
# PhuongAnh-TTS - Stop All Services
# ===========================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}🛑 Đang dừng tất cả services...${NC}"
echo ""

# Kill by PID files
if [ -f "$SCRIPT_DIR/backend/.pid" ]; then
    BACKEND_PID=$(cat "$SCRIPT_DIR/backend/.pid")
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null
        echo -e "${RED}   ❌ Backend (PID: $BACKEND_PID) đã dừng${NC}"
    fi
    rm -f "$SCRIPT_DIR/backend/.pid"
fi

if [ -f "$SCRIPT_DIR/web/.pid" ]; then
    WEB_PID=$(cat "$SCRIPT_DIR/web/.pid")
    if kill -0 "$WEB_PID" 2>/dev/null; then
        kill "$WEB_PID" 2>/dev/null
        echo -e "${RED}   ❌ Web Server (PID: $WEB_PID) đã dừng${NC}"
    fi
    rm -f "$SCRIPT_DIR/web/.pid"
fi

# Kill by process name (fallback)
pkill -f "uvicorn main:app" 2>/dev/null && echo -e "${RED}   ❌ uvicorn đã dừng${NC}" || true
pkill -f "web_server.py" 2>/dev/null && echo -e "${RED}   ❌ web_server đã dừng${NC}" || true

echo ""
echo -e "${GREEN}✅ Tất cả services đã dừng${NC}"
