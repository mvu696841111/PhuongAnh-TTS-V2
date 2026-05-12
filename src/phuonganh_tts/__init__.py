"""
phuonganh_tts — Vietnamese Text-to-Speech Engine

A production-grade Vietnamese TTS library built on transformer-based acoustic
models and neural audio codecs. Supports GPU-optimized inference (LMDeploy),
CPU (GGUF/ONNX), and remote API backends.
"""
import warnings

from phuonganh_tts.factory import PhuongAnh

__version__ = "2.7.0"
__all__ = ["PhuongAnh"]

# Convenience aliases
from phuonganh_tts.factory import PhuongAnh as PhuongAnhTTS
from phuonganh_tts.factory import PhuongAnh as TTS
