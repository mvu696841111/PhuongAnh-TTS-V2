# Hướng dẫn Upload lên GitHub

## Bước 1: Tạo Repository mới trên GitHub

1. Truy cập: https://github.com/new
2. Repository name: `PhuongAnh-TTS`
3. Chọn: **Public**
4. **KHÔNG** chọn "Add a README file", ".gitignore", hoặc license
5. Click **"Create repository"**
6. Sau khi tạo, bạn sẽ thấy trang "Quick setup" - copy URL của repo

## Bước 2: Push code lên GitHub

Thay `YOUR_USERNAME` bằng username GitHub của bạn và `YOUR_REPO_URL` bằng URL vừa copy:

```bash
# Di chuyển vào thư mục dự án
cd /đường/dẫn/đến/PhuongAnh-TTS

# Đổi remote URL (thay YOUR_USERNAME bằng username của bạn)
git remote set-url origin https://github.com/YOUR_USERNAME/PhuongAnh-TTS.git

# Đổi tên branch thành main
git branch -M main

# Push lên GitHub
git push -u origin main
```

## Bước 3: Xác nhận

Kiểm tra repo trên GitHub để xác nhận đã upload thành công.

---

## Lưu ý quan trọng

### Models (1.1GB)
Thư mục `models/` không được upload (đã thêm vào .gitignore). Sau khi clone về, chạy:

```bash
# Cách 1: Tự động download (nếu có internet)
uv sync --group gpu
# Model sẽ được download tự động từ HuggingFace

# Cách 2: Copy thủ công từ máy gốc
# Copy thư mục models/ từ máy cũ sang
```

### Cài đặt trên máy mới

```bash
# 1. Clone repo
git clone https://github.com/YOUR_USERNAME/PhuongAnh-TTS.git
cd PhuongAnh-TTS

# 2. Cài đặt uv (nếu chưa có)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Cài đặt dependencies (GPU mode)
uv sync --group gpu

# 4. Chạy ứng dụng
uv run phuonganh-web
# Hoặc
./start.sh
```

### Cấu hình môi trường

```bash
# Copy file cấu hình mẫu
cp .env.example .env

# Chỉnh sửa .env nếu cần
nano .env
```
