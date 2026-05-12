#!/bin/bash
# ===========================================
# Script cài đặt MongoDB cho PhuongAnh-TTS
# ===========================================

set -e

echo "==========================================="
echo " PhuongAnh-TTS - MongoDB Setup"
echo "==========================================="

# Check if MongoDB is already installed
if command -v mongod &> /dev/null; then
    echo "✓ MongoDB đã được cài đặt"
    mongod --version
else
    echo "MongoDB chưa được cài đặt."
    echo ""
    echo "Vui lòng chọn cách cài đặt:"
    echo ""
    echo "1. Cài Docker Desktop từ: https://docs.docker.com/desktop/"
    echo ""
    echo "2. Hoặc cài MongoDB trực tiếp:"
    echo ""
    echo "   Ubuntu/Debian:"
    echo "   curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg"
    echo "   echo 'deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse' | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list"
    echo "   sudo apt update"
    echo "   sudo apt install -y mongodb-org"
    echo ""
    echo "   Sau đó chạy:"
    echo "   sudo systemctl start mongod"
    echo "   sudo systemctl enable mongod"
    echo ""
fi

echo ""
echo "==========================================="
echo " Sau khi cài đặt MongoDB, chạy script này"
echo "==========================================="
