# 🦜 phuonganh-tts — Vietnamese TTS Studio

> **phuonganh-tts** is a Vietnamese Text-to-Speech model with instant voice cloning and bilingual (English-Vietnamese) support.
> Built on VITS architecture with GGUF/ONNX optimization for efficient inference.

[![Model](https://img.shields.io/badge/Model-phuonganh--tts--v2-blue)](https://huggingface.co/Nemmer/phuonganh-tts-v2)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-v2-blue)](https://huggingface.co/Nemmer/phuonganh-tts-v2)
[![PyPI Version](https://img.shields.io/pypi/v/phuonganh-tts.svg)](https://pypi.org/project/phuonganh-tts/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

---

## Key Features

- **Offline-first** — Local model weights included; no internet required after download
- **Voice cloning** — Clone any voice with 3–5 seconds of reference audio
- **Multi-speaker support** — Pre-built voice presets for various speakers
- **GPU/CPU support** — Optimized for NVIDIA CUDA, Apple Metal, and CPU inference
- **Bilingual support** — English-Vietnamese code-switching capability
- **Clean state management** — No global mutable state; stable under repeated requests

---

## 🚀 Quick Start

### Installation

```bash
# Install via pip
pip install phuonganh-tts

# Or with GPU support
pip install "phuonganh-tts[gpu]"
```

### Usage

```python
from phuonganh_tts import PhuongAnh

# Initialize TTS (uses GGUF/ONNX by default)
tts = PhuongAnh()

# Simple synthesis
text = "Chào bạn. Đây là ví dụ về chuyển văn bản thành giọng nói tiếng Việt."
audio = tts.infer(text=text)

# Save to file
tts.save(audio, "output.wav")
```

---

## 📌 Table of Contents

1. [Installation](#installation)
2. [Python SDK](#sdk)
3. [Web UI](#web-ui)
4. [Docker Deployment](#docker)
5. [Voice Cloning](#cloning)
6. [API Server](#api-server)
7. [Fine-tuning](#finetune)
8. [Support](#support)

---

## 🦜 1. Installation <a name="installation"></a>

### Using `uv` (Recommended)

```bash
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
# Clone the repo
git clone https://github.com/mvu696841111/PhuongAnh-TTS.git
cd PhuongAnh-TTS

# Install with GPU support
uv sync --group gpu

# Or minimal installation (CPU only)
uv sync
```

### Using pip

```bash
pip install phuonganh-tts
```

---

## 📦 2. Python SDK <a name="sdk"></a>

### Basic Usage

```python
from phuonganh_tts import PhuongAnh

# Initialize with default settings
tts = PhuongAnh()

# List available preset voices
voices = tts.list_preset_voices()
for desc, voice_id in voices:
    print(f"Voice: {desc} (ID: {voice_id})")

# Use a specific voice
voice_data = tts.get_preset_voice(voice_id)
audio = tts.infer(text="Xin chào, tôi đang nói bằng giọng mới.", voice=voice_data)
tts.save(audio, "custom_voice.wav")
```

### Voice Cloning <a name="cloning"></a>

Clone any voice with a short audio sample:

```python
from phuonganh_tts import PhuongAnh

tts = PhuongAnh()

# Encode reference audio (3-5 seconds recommended)
my_voice = tts.encode_reference("path/to/reference.wav")

# Synthesize with cloned voice
audio = tts.infer(
    text="Đây là giọng nói được clone.",
    voice=my_voice
)

tts.save(audio, "cloned_voice.wav")
```

---

## 🚀 3. Web UI <a name="web-ui"></a>

Start the Gradio-based web interface:

```bash
# Using uv
uv run phuonganh-web

# Or using the script directly
uv run phuonganh-tts-web
```

Access the UI at `http://127.0.0.1:7860`.

---

## 🐳 4. Docker Deployment <a name="docker"></a>

### Running the Docker Container

```bash
# CPU mode
docker run -p 23333:23333 ghcr.io/mvu696841111/phuonganh-tts:latest

# GPU mode
docker run --gpus all -p 23333:23333 ghcr.io/mvu696841111/phuonganh-tts:latest
```

### Using Docker Compose

```bash
docker-compose up -d
```

---

## 🌐 5. API Server <a name="api-server"></a>

Deploy phuonganh-tts as a REST API server:

```bash
# Start the server
uv run phuonganh-stream
```

The API will be available at `http://localhost:23333`.

### Remote Client Usage

```python
from phuonganh_tts import PhuongAnh

# Connect to remote server
tts = PhuongAnh(
    mode='remote',
    api_base='http://your-server:23333/v1',
    model_name='Nemmer/phuonganh-tts-v2'
)

# Use as normal
audio = tts.infer(text="Remote synthesis example")
tts.save(audio, "remote_output.wav")
```

---

## 🔧 6. Fine-tuning <a name="finetune"></a>

See the [finetune](finetune/) directory for instructions on fine-tuning the model with LoRA or full fine-tuning.

```bash
# See fine-tuning guide
cd finetune
cat README.md
```

---

## 🤝 7. Support & Contact <a name="support"></a>

- **Hugging Face:** [Nemmer/phuonganh-tts-v2](https://huggingface.co/Nemmer/phuonganh-tts-v2)
- **GitHub Issues:** [Report a bug](https://github.com/mvu696841111/PhuongAnh-TTS/issues)
- **License:** Apache 2.0 (Free to use)

---

## 📑 Citation

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

## 🙏 Acknowledgements

This project uses:
- [VITS](https://github.com/jaywalnut310/vits) - VITS: Conditional Variational Autoencoder with Adversarial Learning for End-to-End Text-to-Speech
- [neucodec](https://huggingface.co/neuphonic/neucodec) - Audio decoding
- [sea-g2p](https://github.com/VinAIResearch/sea-g2p) - Grapheme-to-phoneme conversion for Southeast Asian languages

**Made with ❤️ for the Vietnamese TTS community**
