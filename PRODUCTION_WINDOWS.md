# Triển khai PhuongAnh-TTS trên Windows 11 (Production)

## Mục lục

- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt Docker Desktop](#1-cài-đặt-docker-desktop)
- [Clone dự án](#2-clone-dự-án)
- [Build và chạy](#3-build-và-chạy)
- [Truy cập ứng dụng](#4-truy-cập-ứng-dụng)
- [Quản lý container](#5-quản-lý-container)
- [Xử lý sự cố](#6-xử-lý-sự-cố)

---

## Yêu cầu hệ thống

| Thành phần | Yêu cầu tối thiểu | Khuyến nghị |
|------------|-------------------|-------------|
| Hệ điều hành | Windows 11 (64-bit) | Windows 11 Pro |
| RAM | 8 GB | 16 GB |
| Ổ cứng | 20 GB trống | 50 GB SSD |
| CPU | Intel/AMD 4 cores | Intel/AMD 8 cores |
| Docker | Docker Desktop 4.x+ | Docker Desktop 5.x+ |
| WSL2 | Cài đặt sẵn | WSL2 với Ubuntu |

---

## 1. Cài đặt Docker Desktop

### Bước 1.1: Kiểm tra WSL2

Mở **PowerShell** (Admin) và chạy:

```powershell
wsl --status
```

Nếu chưa cài WSL2, cài đặt:

```powershell
wsl --install -d Ubuntu
```

### Bước 1.2: Tải và cài Docker Desktop

1. Tải: https://www.docker.com/products/docker-desktop/
2. Cài đặt Docker Desktop
3. Khi cài xong, khởi động Docker Desktop
4. Đợi icon Docker hiện màu xanh (running)

### Bước 1.3: Bật WSL2 Backend

1. Mở Docker Desktop → Settings → General
2. ✅ Tick **Use WSL 2 instead of Hyper-V** (nếu chưa có)
3. Click **Apply & Restart**

---

## 2. Clone dự án

### Bước 2.1: Mở PowerShell

```powershell
# Di chuyển đến thư mục muốn lưu
cd C:\Projects

# Clone repository
git clone https://github.com/mvu696841111/PhuongAnh-TTS-V2.git
cd PhuongAnh-TTS-V2
```

### Bước 2.2: Kiểm tra cấu trúc thư mục

```powershell
ls
```

Bạn sẽ thấy các thư mục:
```
PhuongAnh-TTS-V2/
├── docker/
├── docker-compose.win.yml  ← File cần dùng
├── models/
├── web/
├── config.yaml
└── ...
```

---

## 3. Build và chạy

### Cách nhanh (Khuyến nghị)

```powershell
# Di chuyển vào thư mục dự án
cd C:\Projects\PhuongAnh-TTS-V2

# Build và chạy (lần đầu sẽ tải models ~1GB)
docker-compose -f docker-compose.win.yml up -d
```

### Build riêng (nếu cần rebuild)

```powershell
# Xóa container cũ (nếu có)
docker-compose -f docker-compose.win.yml down

# Build lại image
docker-compose -f docker-compose.win.yml build --no-cache

# Chạy lại
docker-compose -f docker-compose.win.yml up -d
```

### Lần đầu chạy

Lần đầu tiên sẽ:
1. Build Docker image (~5-10 phút)
2. Tải models từ HuggingFace (~1GB)
3. Khởi động TTS engine (~2-3 phút)

---

## 4. Truy cập ứng dụng

Sau khi container chạy thành công:

**Mở trình duyệt:**
```
http://localhost:7860
```

**Giao diện sẽ hiển thị:**
- Trang web TTS với giao diện tiếng Việt
- Chọn model CPU mặc định
- Nhập văn bản và chuyển thành giọng nói

---

## 5. Quản lý container

### Xem trạng thái

```powershell
# Xem container đang chạy
docker ps

# Xem logs
docker logs -f phuonganh-tts-win
```

### Dừng container

```powershell
# Dừng
docker-compose -f docker-compose.win.yml stop

# Dừng và xóa
docker-compose -f docker-compose.win.yml down
```

### Khởi động lại

```powershell
# Chạy lại (không cần build)
docker-compose -f docker-compose.win.yml start

# Hoặc up/down
docker-compose -f docker-compose.win.yml down
docker-compose -f docker-compose.win.yml up -d
```

### Cập nhật phiên bản mới

```powershell
# Di chuyển vào thư mục
cd C:\Projects\PhuongAnh-TTS-V2

# Pull code mới
git pull origin main

# Rebuild và chạy
docker-compose -f docker-compose.win.yml up -d --build
```

---

## 6. Xử lý sự cố

### Lỗi: Docker Desktop không chạy

**Triệu chứng:** Icon Docker màu đỏ hoặc vàng

**Giải pháp:**
1. Mở **Task Manager** → End Task Docker Desktop
2. Khởi động lại Docker Desktop
3. Nếu lỗi tiếp, vào Settings → Troubleshoot → Reset

### Lỗi: WSL2 not installed

**Triệu chứng:** `WSL 2 installation is incomplete`

**Giải pháp:**
```powershell
wsl --install -d Ubuntu
wsl --set-default-version 2
```

### Lỗi: Port 7860 đã sử dụng

**Triệu chứng:** `port is already allocated`

**Giải pháp:**
```powershell
# Tìm process sử dụng port
netstat -ano | findstr :7860

# Kill process (thay PID)
taskkill /PID <PID> /F
```

### Lỗi: Không đủ RAM

**Triệu chứng:** Container bị kill hoặc crash

**Giải pháp:**
1. Đóng các ứng dụng khác
2. Tăng RAM cho Docker: Docker Desktop → Settings → Resources → Memory: 8GB+

### Lỗi: Build thất bại

**Triệu chứng:** Lỗi khi chạy `docker-compose up`

**Giải pháp:**
```powershell
# Xóa cache và build lại
docker builder prune -a
docker-compose -f docker-compose.win.yml build --no-cache
docker-compose -f docker-compose.win.yml up -d
```

### Lỗi: Models không tải được

**Triệu chứng:** Lỗi kết nối HuggingFace

**Giải pháp:**
1. Kiểm tra internet
2. Nếu bị chặn, dùng VPN
3. Hoặc cấu hình proxy trong Docker

### Xem logs chi tiết

```powershell
# Logs real-time
docker logs -f phuonganh-tts-win

# Logs 100 dòng cuối
docker logs --tail 100 phuonganh-tts-win

# Logs với timestamp
docker logs -t phuonganh-tts-win
```

---

## Cấu hình nâng cao

### Thay đổi port

Chỉnh sửa `docker-compose.win.yml`:

```yaml
services:
  phuonganh-tts:
    ports:
      - "8080:7860"  # Thay 7860 thành 8080
```

### Tăng RAM cho container

Chỉnh sửa `docker-compose.win.yml`:

```yaml
    mem_limit: 16g    # Tăng lên 16GB
    cpu_count: 8      # Tăng lên 8 cores
```

### Bật MongoDB và Redis (tùy chọn)

```yaml
# Trong docker-compose.win.yml, bỏ comment phần mongodb và redis
```

---

## Lệnh hữu ích

| Lệnh | Mô tả |
|------|-------|
| `docker ps` | Xem container đang chạy |
| `docker logs -f phuonganh-tts-win` | Xem logs real-time |
| `docker-compose -f docker-compose.win.yml restart` | Khởi động lại |
| `docker-compose -f docker-compose.win.yml down` | Dừng và xóa |
| `docker exec -it phuonganh-tts-win bash` | Vào terminal container |

---

## Liên hệ hỗ trợ

- **GitHub Issues**: https://github.com/mvu696841111/PhuongAnh-TTS-V2/issues
- **Email**: (thêm email của bạn)

---

## Ghi chú quan trọng

1. **Lần đầu chạy** sẽ tải models nên cần internet và thời gian (5-15 phút)
2. **Model mặc định** đã设为 CPU mode (`phuonganh-tts-v2 Turbo (CPU)`)
3. **Docker Desktop** phải chạy liên tục khi sử dụng app
4. **Data được lưu** trong Docker volumes (không mất khi restart)
