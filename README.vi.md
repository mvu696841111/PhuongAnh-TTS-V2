# 🦜 phuonganh-tts — Vietnamese TTS Studio

> **phuonganh-tts** là mô hình chuyển văn bản thành giọng nói (TTS) tiếng Việt với khả năng **clone giọng nói tức thì** và hỗ trợ **song ngữ Anh-Việt**.
> Được xây dựng trên kiến trúc VITS với tối ưu GGUF/ONNX cho hiệu suất suy luận cao.

[![Model](https://img.shields.io/badge/Model-phuonganh--tts--v2-blue)](https://huggingface.co/Nemmer/phuonganh-tts-v2)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-v2-blue)](https://huggingface.co/Nemmer/phuonganh-tts-v2)
[![PyPI Version](https://img.shields.io/pypi/v/phuonganh-tts.svg)](https://pypi.org/project/phuonganh-tts/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

---

## Tính năng chính

- **Offline-first** — Model được tải về local, không cần internet sau khi cài đặt
- **Clone giọng nói** — Clone bất kỳ giọng nào với 3-5 giây audio tham chiếu
- **Đa giọng nói** — Hỗ trợ nhiều giọng nói có sẵn
- **GPU/CPU** — Tối ưu cho NVIDIA CUDA, Apple Metal, và CPU
- **Hỗ trợ song ngữ** — Anh-Việt code-switching
- **Quản lý trạng thái ổn định** — Không có state global, hoạt động ổn định

---

## 🚀 Bắt đầu nhanh

### Cài đặt

```bash
# Cài qua pip
pip install phuonganh-tts

# Hoặc với hỗ trợ GPU
pip install "phuonganh-tts[gpu]"
```

### Sử dụng

```python
from phuonganh_tts import PhuongAnh

# Khởi tạo TTS (mặc định dùng GGUF/ONNX)
tts = PhuongAnh()

# Chuyển văn bản thành giọng nói
text = "Xin chào. Đây là ví dụ về chuyển văn bản thành giọng nói tiếng Việt."
audio = tts.infer(text=text)

# Lưu file
tts.save(audio, "output.wav")
```

---

## 📌 Mục lục

1. [Cài đặt](#installation)
2. [Python SDK](#sdk)
3. [Giao diện Web](#web-ui)
4. [Docker](#docker)
5. [Clone giọng nói](#cloning)
6. [API Server](#api-server)
7. [Fine-tuning](#finetune)
8. [Hỗ trợ](#support)

---

## 🦜 1. Cài đặt <a name="installation"></a>

### Sử dụng `uv` (Khuyến nghị)

```bash
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
# Clone repo
git clone https://github.com/mvu696841111/PhuongAnh-TTS.git
cd PhuongAnh-TTS

# Cài đặt với GPU
uv sync --group gpu

# Hoặc cài đặt tối thiểu (CPU)
uv sync
```

### Sử dụng pip

```bash
pip install phuonganh-tts
```

---

## 📦 2. Python SDK <a name="sdk"></a>

### Sử dụng cơ bản

```python
from phuonganh_tts import PhuongAnh

# Khởi tạo với cài đặt mặc định
tts = PhuongAnh()

# Liệt kê các giọng có sẵn
voices = tts.list_preset_voices()
for desc, voice_id in voices:
    print(f"Giọng: {desc} (ID: {voice_id})")

# Sử dụng giọng cụ thể
voice_data = tts.get_preset_voice(voice_id)
audio = tts.infer(text="Xin chào, tôi đang nói bằng giọng mới.", voice=voice_data)
tts.save(audio, "custom_voice.wav")
```

### Clone giọng nói <a name="cloning"></a>

Clone bất kỳ giọng nào với mẫu audio ngắn:

```python
from phuonganh_tts import PhuongAnh

tts = PhuongAnh()

# Mã hóa audio tham chiếu (3-5 giây)
my_voice = tts.encode_reference("path/to/reference.wav")

# Tổng hợp với giọng đã clone
audio = tts.infer(
    text="Đây là giọng nói được clone.",
    voice=my_voice
)

tts.save(audio, "cloned_voice.wav")
```

---

## 🚀 3. Giao diện Web <a name="web-ui"></a>

Khởi động giao diện web Gradio:

```bash
# Sử dụng uv
uv run phuonganh-web

# Hoặc chạy script trực tiếp
uv run phuonganh-tts-web
```

Truy cập tại `http://127.0.0.1:7860`.

---

## 🐳 4. Triển khai Docker <a name="docker"></a>

### Chạy Docker Container

```bash
# Chế độ CPU
docker run -p 23333:23333 ghcr.io/mvu696841111/phuonganh-tts:latest

# Chế độ GPU
docker run --gpus all -p 23333:23333 ghcr.io/mvu696841111/phuonganh-tts:latest
```

### Sử dụng Docker Compose

```bash
docker-compose up -d
```

---

## 🌐 5. API Server <a name="api-server"></a>

Triển khai phuonganh-tts như REST API:

```bash
# Khởi động server
uv run phuonganh-stream
```

API sẽ có sẵn tại `http://localhost:23333`.

### Sử dụng từ xa

```python
from phuonganh_tts import PhuongAnh

# Kết nối đến server từ xa
tts = PhuongAnh(
    mode='remote',
    api_base='http://your-server:23333/v1',
    model_name='Nemmer/phuonganh-tts-v2'
)

# Sử dụng bình thường
audio = tts.infer(text="Ví dụ tổng hợp từ xa")
tts.save(audio, "remote_output.wav")
```

---

## 🔧 6. Fine-tuning

Xem thư mục [finetune](finetune/) để biết hướng dẫn fine-tuning với LoRA.

```bash
# Xem hướng dẫn
cd finetune
cat README.md
```

---

## 🤝 7. Hỗ trợ & Liên hệ <a name="support"></a>

- **Hugging Face:** [Nemmer/phuonganh-tts-v2](https://huggingface.co/Nemmer/phuonganh-tts-v2)
- **GitHub Issues:** [Báo lỗi](https://github.com/mvu696841111/PhuongAnh-TTS/issues)
- **Giấy phép:** Apache 2.0 (Miễn phí sử dụng)

---

## 📑 Trích dẫn

```bibtex
@misc{phuonganh-tts2026,
  title        = {phuonganh-tts-v2: Vietnamese Text-to-Speech with Voice Cloning and Bilingual Support},
  author       = {PhuongAnh-TTS Contributors},
  year         = {2026},
  publisher    = {Hugging Face},
  howpublished = {\url{https://huggingface.co/Nemmer/phuonganh-tts-v2}}
}
```

---

## 🙏 Cảm ơn

Dự án này sử dụng:
- [VITS](https://github.com/jaywalnut310/vits) - VITS: Conditional Variational Autoencoder with Adversarial Learning for End-to-End Text-to-Speech
- [neucodec](https://huggingface.co/neuphonic/neucodec) - Audio decoding
- [sea-g2p](https://github.com/VinAIResearch/sea-g2p) - Grapheme-to-phoneme conversion for Southeast Asian languages

**Được làm với ❤️ cho cộng đồng TTS tiếng Việt**
