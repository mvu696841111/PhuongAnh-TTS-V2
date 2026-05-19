# PROMPT CHO AI AGENT - Triển khai PhuongAnh-TTS trên Windows

---

## 📋 Prompt để dán vào AI Agent

```
Tôi vừa clone dự án PhuongAnh-TTS về máy Windows 11 của tôi.

## Thông tin máy:
- Hệ điều hành: Windows 11
- CPU: Intel/AMD (không có GPU)
- RAM: 8GB/16GB
- Đã cài Docker Desktop với WSL2 backend
- Cổng 7860 đang trống

## Yêu cầu:
Triển khai và chạy PhuongAnh-TTS trên máy tôi bằng Docker (CPU mode).

## Hướng dẫn thực hiện:

Hãy đọc các file sau theo thứ tự để hiểu cấu trúc dự án và cách triển khai:

1. Đọc PRODUCTION_WINDOWS.md - Hướng dẫn triển khai production
2. Đọc docker-compose.win.yml - File cấu hình Docker cho Windows
3. Đọc docker/Dockerfile.win - Docker image configuration
4. Đọc TROUBLESHOOTING_WINDOWS.md - Xử lý sự cố nếu gặp lỗi
5. Đọc pyproject.toml - Kiểm tra dependencies

## Các bước cần thực hiện:

1. **Kiểm tra cấu trúc dự án**
   - Xem có file docker-compose.win.yml không
   - Xem có thư mục docker/ không
   - Kiểm tra Dockerfile

2. **Build Docker image**
   - Chạy lệnh build với docker-compose.win.yml
   - Đợi image được build thành công

3. **Chạy container**
   - Start container từ image đã build
   - Kiểm tra container có đang chạy không

4. **Truy cập ứng dụng**
   - Mở trình duyệt http://localhost:7860
   - Xác nhận web UI hiển thị đúng

5. **Xử lý lỗi nếu có**
   - Nếu gặp lỗi, đọc TROUBLESHOOTING_WINDOWS.md
   - Thực hiện các bước fix theo hướng dẫn

## Lệnh cần chạy:

```powershell
# Di chuyển vào thư mục dự án
cd C:\đường\dẫn\đến\PhuongAnh-TTS-V2

# Build và chạy
docker-compose -f docker-compose.win.yml up -d

# Kiểm tra trạng thái
docker ps

# Xem logs nếu cần
docker logs -f phuonganh-tts-win
```

## Kết quả mong đợi:
- Container đang chạy (status: Up)
- Truy cập http://localhost:7860 thành công
- Giao diện web hiển thị với các model TTS tiếng Việt

Hãy thực hiện từng bước và báo cáo kết quả cho tôi.
```

---

## 🔧 Prompt ngắn gọn (nếu agent đã quen thuộc)

```
Deploy PhuongAnh-TTS on Windows 11 using Docker (CPU mode).

Read these files:
- PRODUCTION_WINDOWS.md
- docker-compose.win.yml
- docker/Dockerfile.win

Build: `docker-compose -f docker-compose.win.yml up -d`
Access: http://localhost:7860
```

---

## 📌 Ghi chú khi dùng

1. Copy toàn bộ prompt (hoặc phiên bản ngắn)
2. Dán vào AI agent (Cursor, Claude, ChatGPT, v.v.)
3. AI agent sẽ đọc các file trong dự án và hướng dẫn chi tiết
4. Làm theo từng bước agent chỉ ra
