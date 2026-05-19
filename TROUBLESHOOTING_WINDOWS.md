# 🔧 Form Tự Xử Lý Sự Cố - PhuongAnh-TTS

## Hướng dẫn sử dụng

1. Đọc từng bước từ trên xuống
2. Tick ✅ ô đã hoàn thành
3. Làm bước tiếp theo nếu vấn đề chưa được giải quyết

---

## ❓ Bạn đang gặp vấn đề gì?

### A. Docker Desktop không chạy được

**Triệu chứng:** Icon Docker màu đỏ, vàng, hoặc báo lỗi

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Restart Docker Desktop** | ☐ |
|   | Đóng Docker Desktop → Mở lại → Đợi icon xanh | |
| 2 | **Restart máy tính** | ☐ |
|   | Restart Windows → Mở Docker Desktop lại | |
| 3 | **Kiểm tra WSL2** | ☐ |
|   | Mở PowerShell (Admin): `wsl --status` | |
|   | Nếu lỗi: `wsl --install -d Ubuntu` | |
| 4 | **Reset Docker** | ☐ |
|   | Docker Desktop → Settings → Troubleshoot → Reset | |

**Nếu vẫn lỗi:** Gửi ảnh lỗi lên nhóm hỗ trợ

---

### B. Build Docker thất bại

**Triệu chứng:** Lỗi khi chạy `docker-compose up --build`

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Kiểm tra đã pull code mới nhất** | ☐ |
|   | `git pull origin main` | |
| 2 | **Xóa cache Docker** | ☐ |
|   | `docker builder prune -a` | |
|   | `docker system prune -a` | |
| 3 | **Rebuild không cache** | ☐ |
|   | `docker-compose -f docker-compose.win.yml build --no-cache` | |

**Lỗi thường gặp:**

| Lỗi | Giải pháp |
|------|-----------|
| `src not found` | Pull code mới: `git pull origin main` |
| `uv sync failed` | Kiểm tra pyproject.toml có trong thư mục |
| `license warning` | Bỏ qua (chỉ là warning, không ảnh hưởng) |

---

### C. Container chạy nhưng không truy cập được web

**Triệu chứng:** Container đang chạy nhưng http://localhost:7860 không mở

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Kiểm tra container đang chạy** | ☐ |
|   | `docker ps` → thấy `phuonganh-tts-win` | |
| 2 | **Đợi khởi động** | ☐ |
|   | Đợi 2-3 phút sau khi container bắt đầu | |
| 3 | **Kiểm tra logs** | ☐ |
|   | `docker logs phuonganh-tts-win` | |
|   | Xem có lỗi gì không | |
| 4 | **Kiểm tra port** | ☐ |
|   | `netstat -ano \| findstr 7860` | |
|   | Thấy 0.0.0.0:7860 là OK | |
| 5 | **Restart container** | ☐ |
|   | `docker restart phuonganh-tts-win` | |

---

### D. Không tải được models

**Triệu chứng:** Lỗi "Model not found" hoặc tải rất chậm

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Kiểm tra internet** | ☐ |
|   | Mở trình duyệt, thử truy cập google.com | |
| 2 | **Tắt tường lửa tạm thời** | ☐ |
|   | Windows Security → Firewall → Tắt tạm | |
| 3 | **Sử dụng VPN** (nếu bị chặn) | ☐ |
|   | Bật VPN → Build lại | |
| 4 | **Tăng timeout** | ☐ |
|   | Chỉnh `timeout: 300s` trong docker-compose | |
| 5 | **Kiểm tra disk space** | ☐ |
|   | Còn trên 10GB trống không? | |

---

### E. RAM/CPU quá tải

**Triệu chứng:** Máy chạy chậm, container bị kill

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Kiểm tra RAM** | ☐ |
|   | Task Manager → Performance → Memory | |
|   | Dùng dưới 90% RAM | |
| 2 | **Tăng RAM cho Docker** | ☐ |
|   | Docker Desktop → Settings → Resources | |
|   | Memory: 8GB → 16GB | |
| 3 | **Giảm CPU cores** | ☐ |
|   | Trong docker-compose: `cpu_count: 4` thay vì 8 | |
| 4 | **Đóng ứng dụng khác** | ☐ |
|   | Đóng Chrome, game, ứng dụng nặng | |
| 5 | **Dùng model nhẹ hơn** | ☐ |
|   | Trong config.yaml: `phuonganh-tts-v2 Turbo (CPU)` | |

---

### F. Lỗi Port đã sử dụng

**Triệu chứng:** `port is already allocated`

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Tìm process sử dụng port** | ☐ |
|   | `netstat -ano \| findstr 7860` | |
| 2 | **Kill process đó** | ☐ |
|   | `taskkill /PID <số PID> /F` | |
| 3 | **Hoặc đổi port khác** | ☐ |
|   | Sửa `7860:7860` thành `8080:7860` | |

---

### G. Container bị dừng liên tục

**Triệu chứng:** Container chạy được vài phút rồi dừng

| # | Bước kiểm tra | Trạng thái |
|---|---------------|------------|
| 1 | **Xem logs lỗi** | ☐ |
|   | `docker logs phuonganh-tts-win --tail 50` | |
| 2 | **Kiểm tra disk space** | ☐ |
|   | Ổ C: còn trên 10GB? | |
| 3 | **Kiểm tra RAM** | ☐ |
|   | Docker Desktop → Resources → Memory | |
| 4 | **Xóa volumes cũ** | ☐ |
|   | `docker volume prune` | |
| 5 | **Dừng MongoDB/Redis nếu không cần** | ☐ |
|   | Comment out trong docker-compose.yml | |

---

## 📋 Checklist Trước Khi Yêu Cầu Hỗ Trợ

Đã làm tất cả các bước sau:

| # | Checklist | ✅ |
|---|-----------|---|
| 1 | Restart Docker Desktop | ☐ |
| 2 | Restart máy tính | ☐ |
| 3 | Pull code mới nhất (`git pull origin main`) | ☐ |
| 4 | Xóa cache và rebuild (`docker builder prune -a`) | ☐ |
| 5 | Kiểm tra logs (`docker logs phuonganh-tts-win`) | ☐ |
| 6 | Kiểm tra đủ RAM/Disk | ☐ |
| 7 | Đợi đủ thời gian (5-15 phút lần đầu) | ☐ |

---

## 📞 Khi Liên Hệ Hỗ Trợ

Cung cấp thông tin sau:

1. **Ảnh lỗi** (chụp màn hình terminal/PowerShell)
2. **Kết quả lệnh:**
   ```
   docker ps
   docker logs phuonganh-tts-win --tail 30
   ```
3. **Phiên bản:**
   ```
   docker --version
   wsl --version
   ```
4. **RAM và Disk** còn trống bao nhiêu?

---

## ✅ Checklist Hoàn Thành

- [ ] Đã triển khai thành công
- [ ] Truy cập được http://localhost:7860
- [ ] TTS hoạt động bình thường
- [ ] Docker tự khởi động khi mở máy

---

## 💡 Mẹo Hay

1. **Không tắt Docker Desktop** khi đang dùng app
2. **Tạo shortcut** để chạy nhanh:
   ```powershell
   # Tạo shortcut với lệnh:
   docker-compose -f docker-compose.win.yml up -d
   ```
3. **Backup volumes** định kỳ nếu có data quan trọng
4. **Update định kỳ**:
   ```powershell
   git pull origin main
   docker-compose -f docker-compose.win.yml up -d --build
   ```
