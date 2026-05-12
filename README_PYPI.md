# 🦜 phuonganh-tts

**phuonganh-tts** is a Vietnamese Text-to-Speech (TTS) model with **instant voice cloning** and **English-Vietnamese bilingual** support.

[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-v2-blue)](https://huggingface.co/Nemmer/phuonganh-tts-v2)
[![PyPI](https://img.shields.io/pypi/v/phuonganh-tts.svg)](https://pypi.org/project/phuonganh-tts/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](https://opensource.org/licenses/Apache-2.0)

## Key Features
- **Bilingual (English-Vietnamese)**: Seamless code-switching support
- **Instant Voice Cloning**: Clone any voice with just 3-5s of reference audio
- **Ultra-Fast Inference**: Optimized for CPU (GGUF) and GPU (LMDeploy)
- **Production Ready**: High-fidelity 24 kHz audio generation, fully offline

---

## Quick Install

```bash
pip install phuonganh-tts

# With GPU support
pip install "phuonganh-tts[gpu]"
```

---

## Quick Start (Python SDK)

```python
from phuonganh_tts import PhuongAnh

# Initialize
tts = PhuongAnh()

# Simple synthesis
text = "Xin chào. Đây là ví dụ về chuyển văn bản thành giọng nói."
audio = tts.infer(text=text)
tts.save(audio, "output.wav")

# Using a specific Preset Voice
voices = tts.list_preset_voices()
voice_data = tts.get_preset_voice(voices[0][1])
audio = tts.infer(text="Tôi đang nói bằng giọng mới.", voice=voice_data)
tts.save(audio, "custom_voice.wav")
```

### Zero-shot Voice Cloning

```python
from phuonganh_tts import PhuongAnh

tts = PhuongAnh()

# Encode reference audio (3-5s wav/mp3)
my_voice = tts.encode_reference("path/to/voice.wav")

# Synthesize with cloned voice
audio = tts.infer(text="Đây là giọng của tôi.", voice=my_voice)
tts.save(audio, "cloned.wav")
```

---

## Model Overview

| Model | Format | Device | Bilingual |
|---|---|---|---|
| **phuonganh-tts-v2** | PyTorch/GGUF | GPU/CPU | ✅ |
| **phuonganh-tts** | PyTorch | GPU/CPU | ✅ |

---

## Support & Links
- **GitHub:** [mvu696841111/PhuongAnh-TTS](https://github.com/mvu696841111/PhuongAnh-TTS)
- **Hugging Face:** [Nemmer/phuonganh-tts-v2](https://huggingface.co/Nemmer/phuonganh-tts-v2)

**Made with ❤️ for the Vietnamese TTS community**
