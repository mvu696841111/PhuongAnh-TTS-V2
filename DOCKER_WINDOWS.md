# Hướng dẫn cài đặt PhuongAnh-TTS trên Windows 11 với Docker

## Mục lục

1. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
2. [Cài đặt Docker Desktop trên Windows 11](#cài-đặt-docker-desktop-trên-windows-11)
3. [Clone dự án từ GitHub](#clone-dự-án-từ-github)
4. [Build và chạy với Docker](#build-và-chạy-với-docker)
5. [Sử dụng ứng dụng](#sử-dụng-ứng-dụng)
6. [GPU Acceleration (NVIDIA)](#gpu-acceleration-nvidia)
7. [Xử lý sự cố](#xử-lý-sự-cố)

---

## Yêu cầu hệ thống

### Tối thiểu (CPU)
- Windows 11 Pro/Enterprise (64-bit)
- 8GB RAM (khuyến nghị 16GB)
- 10GB dung lượng trống
- Docker Desktop 4.25+

### Khuyến nghị (GPU)
- NVIDIA GPU với CUDA support
- NVIDIA Driver 525.60.13+
- 16GB RAM
- 15GB dung lượng trống

---

## Cài đặt Docker Desktop trên Windows 11

### Bước 1: Kích hoạt WSL 2

Mở PowerShell (Admin) và chạy:

```powershell
wsl --install
```

Sau khi cài đặt, khởi động lại máy.

### Bước 2: Tải và cài đặt Docker Desktop

1. Tải Docker Desktop từ: https://www.docker.com/products/docker-desktop
2. Chạy file cài đặt
3. Chọn **Use WSL 2 instead of Hyper-V** (được khuyến nghị)
4. Hoàn tất cài đặt

### Bước 3: Xác nhận Docker hoạt động

Mở PowerShell và chạy:

```powershell
docker --version
docker-compose --version
docker run hello-world
```

---

## Clone dự án từ GitHub

Mở Terminal (PowerShell hoặc Command Prompt) và chạy:

```powershell
# Di chuyển đến thư mục muốn lưu dự án
cd C:\Projects

# Clone repository
git clone https://github.com/mvu696841111/PhuongAnh-TTS-V2.git
cd PhuongAnh-TTS-V2
```

---

## Build và chạy với Docker

### Cách 1: Sử dụng Docker Compose (Khuyến nghị)

```powershell
# Build và chạy tất cả services (TTS + MongoDB + Redis)
docker-compose -f docker-compose.win.yml up -d

# Xem logs
docker-compose -f docker-compose.win.yml logs -f

# Dừng services
docker-compose -f docker-compose.win.yml down
```

### Cách 2: Chỉ chạy Web UI

```powershell
# Build image
docker build -t phuonganh-tts -f docker/Dockerfile.win .

# Chạy container
docker run -p 7860:7860 --name phuonganh-tts phuonganh-tts
```

### Cách 3: Với GPU NVIDIA

```powershell
# Build với GPU support
docker build -t phuonganh-tts-gpu -f docker/Dockerfile.gpu .

# Chạy với GPU
docker run --gpus all -p 7860:7860 --name phuonganh-tts phuonganh-tts-gpu
```

---

## Sử dụng ứng dụng

### Truy cập Web UI

1. Mở trình duyệt web
2. Truy cập: **http://localhost:7860**

### Các tính năng chính

- **Text-to-Speech**: Nhập văn bản tiếng Việt/Anh để chuyển thành giọng nói
- **Voice Cloning**: Upload audio mẫu để clone giọng nói
- **Preset Voices**: Chọn từ các giọng nói có sẵn

### Lưu trữ dữ liệu

Dữ liệu được lưu trong Docker volumes:
- **phuonganh_models**: Lưu trữ model đã download
- **phuonganh_outputs**: Lưu trữ file audio đã tạo

---

## GPU Acceleration (NVIDIA)

### Yêu cầu

1. NVIDIA GPU với driver mới nhất
2. NVIDIA Container Toolkit đã cài đặt

### Cài đặt NVIDIA Container Toolkit

```powershell
# Thêm NVIDIA repository
wsl -t Ubuntu
wsl --install -d Ubuntu

# Trong WSL terminal
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://gcr.io/tekton-workspace#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Chạy với GPU

```powershell
docker-compose -f docker-compose.win.yml up -d phuonganh-tts
```

Kiểm tra GPU usage:

```powershell
docker exec -it phuonganh-tts nvidia-smi
```

---

## Xử lý sự cố

### Lỗi "WSL 2 installation is incomplete"

```powershell
# Cài đặt WSL 2 kernel update
wsl --update

# Hoặc cài đặt thủ công
# Tải từ: https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi
```

### Lỗi "Docker daemon is not running"

```powershell
# Khởi động Docker Desktop
# Hoặc trong PowerShell
Start-Service Docker
```

### Lỗi RAM không đủ

```powershell
# Tăng giới hạn RAM trong Docker Desktop
# Settings > Resources > Memory > 8GB (hoặc cao hơn)
```

### Lỗi port đã sử dụng

```powershell
# Kiểm tra port đang sử dụng
netstat -ano | findstr :7860

# Hoặc thay đổi port trong docker-compose.win.yml
```

### Container không khởi động được

```powershell
# Xem logs
docker logs phuonganh-tts-win

# Xóa và tạo lại container
docker rm -f phuonganh-tts-win
docker-compose -f docker-compose.win.yml up -d
```

### Khắc phục lỗi Network

```powershell
# Reset Docker networking
docker network prune

# Hoặc restart Docker Desktop
```

---

## Lệnh hữu ích

```powershell
# Xem tất cả containers
docker ps -a

# Xem logs real-time
docker logs -f phuonganh-tts-win

# Truy cập vào container
docker exec -it phuonganh-tts-win bash

# Stop container
docker stop phuonganh-tts-win

# Xóa container
docker rm phuonganh-tts-win

# Xóa image
docker rmi phuonganh-tts

# Xem disk usage
docker system df

# Cleanup không gian đĩa
docker system prune -a
```

---

## Cập nhật dự án

```powershell
# Pull code mới nhất
git pull origin main

# Rebuild image
docker-compose -f docker-compose.win.yml build --no-cache

# Restart services
docker-compose -f docker-compose.win.yml up -d
```

---

## Liên hệ & Hỗ trợ

- **GitHub Issues**: https://github.com/mvu696841111/PhuongAnh-TTS-V2/issues
- **Documentation**: https://github.com/mvu696841111/PhuongAnh-TTS-V2#readme
