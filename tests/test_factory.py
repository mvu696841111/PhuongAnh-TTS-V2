import pytest
import sys
from unittest.mock import patch, MagicMock

# Mock heavy modules before importing PhuongAnh
mock_torch = MagicMock()
mock_torch.Tensor = MagicMock
sys.modules["torch"] = mock_torch
sys.modules["torch.backends"] = mock_torch.backends
sys.modules["torch.backends.mps"] = mock_torch.backends.mps
sys.modules["llama_cpp"] = MagicMock()
sys.modules["lmdeploy"] = MagicMock()
sys.modules["neucodec"] = MagicMock()
sys.modules["transformers"] = MagicMock()
sys.modules["peft"] = MagicMock()

from phuonganh_tts.factory import PhuongAnh

@patch("phuonganh_tts.turbo.TurboPhuongAnhTTS", create=True)
def test_factory_turbo(mock_turbo):
    PhuongAnh(mode="turbo")
    mock_turbo.assert_called_once()

@patch("phuonganh_tts.turbo.TurboGPUPhuongAnhTTS", create=True)
def test_factory_turbo_gpu(mock_turbo_gpu):
    PhuongAnh(mode="turbo_gpu")
    mock_turbo_gpu.assert_called_once()

@patch("phuonganh_tts.fast.FastPhuongAnhTTS", create=True)
def test_factory_fast(mock_fast):
    PhuongAnh(mode="fast")
    mock_fast.assert_called_once()

@patch("phuonganh_tts.standard.PhuongAnhTTS", create=True)
def test_factory_standard(mock_standard):
    PhuongAnh(mode="standard")
    mock_standard.assert_called_once()

@patch("phuonganh_tts.remote.RemotePhuongAnhTTS", create=True)
def test_factory_remote(mock_remote):
    PhuongAnh(mode="remote")
    mock_remote.assert_called_once()

@patch("phuonganh_tts.core_xpu.XPUPhuongAnhTTS", create=True)
def test_factory_xpu(mock_xpu):
    PhuongAnh(mode="xpu")
    mock_xpu.assert_called_once()

def test_factory_invalid_mode():
    assert PhuongAnh(mode="unknown") is None
