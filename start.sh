#!/bin/bash
# ===========================================
# PhuongAnh-TTS - Start All Services
# Chạy cả Web Frontend + Backend API
# ===========================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Đang dừng tất cả services...${NC}"

    # Kill backend
    if [ -f "$SCRIPT_DIR/backend/.pid" ]; then
        BACKEND_PID=$(cat "$SCRIPT_DIR/backend/.pid")
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            kill "$BACKEND_PID" 2>/dev/null
            echo -e "${RED}   ❌ Backend đã dừng${NC}"
        fi
        rm -f "$SCRIPT_DIR/backend/.pid"
    fi

    # Kill web
    if [ -f "$SCRIPT_DIR/web/.pid" ]; then
        WEB_PID=$(cat "$SCRIPT_DIR/web/.pid")
        if kill -0 "$WEB_PID" 2>/dev/null; then
            kill "$WEB_PID" 2>/dev/null
            echo -e "${RED}   ❌ Web Server đã dừng${NC}"
        fi
        rm -f "$SCRIPT_DIR/web/.pid"
    fi

    # Kill by port
    fuser -k 8000/tcp 2>/dev/null || true
    fuser -k 3000/tcp 2>/dev/null || true

    echo ""
    echo -e "${GREEN}✅ Tất cả services đã dừng${NC}"
    exit 0
}

# Trap Ctrl+C
trap cleanup SIGINT SIGTERM

# Kill existing services
echo -e "${YELLOW}🔄 Dọn dẹp processes cũ...${NC}"

# Kill by PID files
[ -f "$SCRIPT_DIR/backend/.pid" ] && kill $(cat "$SCRIPT_DIR/backend/.pid") 2>/dev/null || true
[ -f "$SCRIPT_DIR/web/.pid" ] && kill $(cat "$SCRIPT_DIR/web/.pid") 2>/dev/null || true
rm -f "$SCRIPT_DIR/backend/.pid" "$SCRIPT_DIR/web/.pid"

# Kill by process name
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "web_server.py" 2>/dev/null || true

# Kill by port
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true

sleep 2

echo ""
echo -e "${CYAN}=========================================="
echo "🚀 PHUONGANH-TTS - STARTING ALL SERVICES"
echo -e "==========================================${NC}"
echo ""

# Check model
if [ ! -d "models/phuonganh-tts-v2" ]; then
    echo -e "${RED}❌ Error: Local model not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Local model: ./models/phuonganh-tts-v2${NC}"

if [ ! -d "models/neucodec-onnx-decoder-int8" ]; then
    echo -e "${RED}❌ Error: Codec not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Local codec: ./models/neucodec-onnx-decoder-int8${NC}"
echo ""

# Enable offline mode
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_SYMLINKS=1

# Create directories
mkdir -p "$SCRIPT_DIR/data/audios"
mkdir -p "$SCRIPT_DIR/data/temp"
mkdir -p "$SCRIPT_DIR/data/mongodb"
mkdir -p "$SCRIPT_DIR/data/redis"

# ==========================================
# START BACKEND using local venv
# ==========================================
echo -e "${CYAN}📦 Starting Backend API...${NC}"

# Load env
if [ -f "$SCRIPT_DIR/backend/.env" ]; then
    export $(cat "$SCRIPT_DIR/backend/.env" | grep -v '^#' | xargs)
fi

cd "$SCRIPT_DIR/backend"
export PYTHONPATH="$SCRIPT_DIR/backend"
"$SCRIPT_DIR/.venv/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo $BACKEND_PID > "$SCRIPT_DIR/backend/.pid"
echo -e "${GREEN}   ✅ Backend chạy tại http://localhost:8000 (PID: $BACKEND_PID)${NC}"

cd "$SCRIPT_DIR"

# Wait for backend
echo -e "${YELLOW}   ⏳ Đợi backend khởi động...${NC}"
for i in {1..15}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}   ✅ Backend ready!${NC}"
        break
    fi
    sleep 1
done

echo ""

# ==========================================
# START WEB FRONTEND using local venv
# ==========================================
echo -e "${CYAN}🌐 Starting Web Frontend...${NC}"

cd "$SCRIPT_DIR/web"
export PORT=3000
"$SCRIPT_DIR/.venv/bin/python" web_server.py &
WEB_PID=$!
echo $WEB_PID > "$SCRIPT_DIR/web/.pid"
echo -e "${GREEN}   ✅ Web chạy tại http://localhost:3000 (PID: $WEB_PID)${NC}"

echo ""
echo -e "${CYAN}=========================================="
echo "🎉 TẤT CẢ SERVICES ĐÃ SẴN SÀNG!"
echo -e "==========================================${NC}"
echo ""
echo -e "  🌐 Web UI:     ${GREEN}http://localhost:3000${NC}"
echo -e "  📦 API:        ${GREEN}http://localhost:8000${NC}"
echo -e "  📖 Swagger:    ${GREEN}http://localhost:8000/docs${NC}"
echo ""
echo -e "${YELLOW}Nhấn Ctrl+C để dừng tất cả services${NC}"
echo ""

# Wait for any process to exit
wait $BACKEND_PID $WEB_PID
