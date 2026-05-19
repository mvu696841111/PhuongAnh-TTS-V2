# Hướng dẫn cài đặt PhuongAnh-TTS trên Windows 11 (không dùng Docker)

## Mục lục

1. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
2. [Cài đặt Python](#cài-đặt-python)
3. [Cài đặt Git](#cài-đặt-git)
4. [Clone dự án](#clone-dự-án)
5. [Cài đặt uv và dependencies](#cài-đặt-uv-và-dependencies)
6. [Download models](#download-models)
7. [Chạy ứng dụng](#chạy-ứng-dụng)
8. [Xử lý sự cố](#xử-lý-sự-cố)

---

## Yêu cầu hệ thống

- **Windows 11** (64-bit)
- **8GB RAM** (khuyến nghị 16GB)
- **10GB dung lượng trống**
- **Python 3.10 hoặc 3.11, 3.12**

---

## Cài đặt Python

1. Tải Python từ: https://www.python.org/downloads/windows/
2. Chọn phiên bản **Python 3.12** (khuyến nghị)
3. Khi cài đặt, **tick chọn**:
   - ☑️ Add Python to PATH
   - ☑️ Add Python to environment variables
4. Click **Install Now**

Kiểm tra cài đặt:

```powershell
python --version
pip --version
```

---

## Cài đặt Git

1. Tải Git từ: https://git-scm.com/download/win
2. Cài đặt với cấu hình mặc định
3. Kiểm tra:

```powershell
git --version
```

---

## Clone dự án

```powershell
# Di chuyển đến thư mục muốn lưu
cd C:\Projects

# Clone repository
git clone https://github.com/mvu696841111/PhuongAnh-TTS-V2.git
cd PhuongAnh-TTS-V2
```

---

## Cài đặt uv và dependencies

### Cách 1: Sử dụng uv (Khuyến nghị - nhanh hơn)

```powershell
# Cài đặt uv (trình quản lý package nhanh)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Di chuyển vào thư mục dự án
cd C:\Projects\PhuongAnh-TTS-V2

# Cài đặt dependencies (CPU mode)
uv sync --group gpu

# Hoặc cài đặt không có GPU (nhanh hơn, ít dependencies)
uv sync
```

### Cách 2: Sử dụng pip

```powershell
cd C:\Projects\PhuongAnh-TTS-V2

# Cài đặt dependencies
pip install -r requirements_xpu.txt

# Hoặc cài đặt từ pyproject.toml
pip install -e .
```

---

## Download models

Sau khi cài đặt, models sẽ được download tự động khi chạy app lần đầu.

Hoặc download thủ công:

```powershell
# Tạo thư mục models
mkdir models

# Download model chính
# (Models sẽ được download khi chạy ứng dụng lần đầu)
```

**Lưu ý**: Models có thể nặng ~1GB, cần internet để download từ HuggingFace.

---

## Chạy ứng dụng

### Cách 1: Chạy Web UI (Khuyến nghị)

```powershell
cd C:\Projects\PhuongAnh-TTS-V2

# Chạy web UI
uv run phuonganh-web

# Hoặc
python -m phuonganh_app.gradio_main
```

Sau đó mở trình duyệt: **http://localhost:7860**

### Cách 2: Chạy Backend API + Frontend

```powershell
cd C:\Projects\PhuongAnh-TTS-V2

# Terminal 1: Chạy Backend API
uv run phuonganh-stream

# Terminal 2: Chạy Frontend Web
uv run phuonganh-frontend
```

Truy cập:
- Frontend: **http://localhost:3000**
- Backend API: **http://localhost:8000**

---

## Xử lý sự cố

### Lỗi "Python is not recognized"

```powershell
# Kiểm tra Python đã được thêm vào PATH
# Thử khởi động lại Terminal

# Hoặc tìm đường dẫn Python
where python
```

### Lỗi "uv is not recognized"

```powershell
# Khởi động lại Terminal sau khi cài uv
# Hoặc thêm uv vào PATH thủ công
```

### Lỗi "Microsoft Visual C++ Required"

Tải và cài đặt: https://aka.ms/vs/17/release/vc_redist.x64.exe

### Lỗi RAM không đủ

```powershell
# Tăng virtual memory
# Settings > System > About > Advanced system settings > Performance > Settings > Advanced > Virtual memory
```

### Lỗi port đã sử dụng

```powershell
# Tìm process sử dụng port
netstat -ano | findstr :7860

# Kill process (thay PID bằng số)
taskkill /PID <PID> /F
```

### Lỗi download model chậm

Đảm bảo:
- Internet ổn định
- Không bị chặn bởi firewall
- Thử sử dụng VPN nếu cần

---

## Lệnh hữu ích

```powershell
# Cập nhật dự án
git pull origin main

# Cài lại dependencies
uv sync --refresh

# Xem logs (nếu có)
Get-Content logs/app.log -Wait
```

---

## Liên hệ

- **GitHub Issues**: https://github.com/mvu696841111/PhuongAnh-TTS-V2/issues
