"""
Model lifecycle manager for phuonganh-tts.

Responsibilities:
- Cache-first loading (check HuggingFace local cache first)
- Single-load with thread locking (prevent concurrent load requests)
- Backend selection based on hardware
- Graceful fallback when GPU unavailable
- Auto-load of phuonganh-tts (GPU) on startup
"""
from __future__ import annotations

import os
import threading
import logging
from dataclasses import dataclass
from typing import Optional, Any, Callable

import torch

logger = logging.getLogger("phuonganh.model_manager")


# ── Configurations ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BackboneConfig:
    display_name: str
    repo_id: str
    supports_streaming: bool = False
    is_gguf: bool = False
    gguf_filename: Optional[str] = None
    default_codec: str = ""


@dataclass(frozen=True)
class CodecConfig:
    display_name: str
    repo_id: str
    is_onnx: bool = False


# Default model — phuonganh-tts (local)
AVAILABLE_BACKBONES: dict[str, BackboneConfig] = {
    "phuonganh-tts-v2 (Local)": BackboneConfig(
        display_name="phuonganh-tts-v2 (Local)",
        repo_id="./models/phuonganh-tts-v2",
        supports_streaming=False,
        is_gguf=False,
        default_codec="NeuCodec (ONNX)",
    ),
    "phuonganh-tts-v2 GGUF (Local)": BackboneConfig(
        display_name="phuonganh-tts-v2 GGUF (Local)",
        repo_id="./models/phuonganh-tts-v2",
        supports_streaming=True,
        is_gguf=True,
        gguf_filename="phuonganh-tts-v2-Q4-K-M.gguf",
        default_codec="NeuCodec (ONNX)",
    ),
}

AVAILABLE_CODECS: dict[str, CodecConfig] = {
    "NeuCodec (ONNX)": CodecConfig(
        display_name="NeuCodec (ONNX)",
        repo_id="./models/neucodec-onnx-decoder-int8",
        is_onnx=True,
    ),
}


# ── Hardware Detection ───────────────────────────────────────────────────────

def detect_device() -> tuple[str, str]:
    """Detect the best available compute device."""
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu", "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps", "mps"
    if torch.cuda.is_available():
        return "cuda", "cuda"
    return "cpu", "cpu"


def has_gpu() -> bool:
    """True if any GPU (CUDA, MPS, XPU) is available."""
    dev, _ = detect_device()
    return dev in ("cuda", "mps", "xpu")


# ── Pre-download Utilities ─────────────────────────────────────────────────

def _pre_download_codec(codec_cfg: CodecConfig, report: Callable[[str], None]) -> None:
    """Download codec to local cache if not already cached."""
    try:
        from huggingface_hub import snapshot_download
        report(f"📥 Đang tải codec '{codec_cfg.display_name}' về cache...")
        snapshot_download(
            repo_id=codec_cfg.repo_id,
            local_files_only=False,
            allow_patterns=["*.bin", "*.pt", "*.onnx", "config.json"]
            if not codec_cfg.is_onnx
            else ["*.onnx", "*.json"],
        )
        report(f"✅ Codec '{codec_cfg.display_name}' đã được cache.")
    except Exception as e:
        report(f"⚠️ Không thể cache codec: {e}")


# ── Cache Utilities ─────────────────────────────────────────────────────────

def is_model_cached(repo_id: str, filename: Optional[str] = None) -> bool:
    """Check if a model is already in the HuggingFace local cache."""
    try:
        from huggingface_hub import snapshot_download
        cache_dir = snapshot_download(
            repo_id=repo_id,
            local_files_only=True,
            allow_patterns=[filename] if filename else None,
        )
        if cache_dir and os.path.exists(cache_dir):
            if filename:
                return os.path.exists(os.path.join(cache_dir, filename))
            return True
    except Exception:
        pass
    return False


def is_voices_json_cached(repo_id: str) -> bool:
    """Check if voices.json is cached locally."""
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=repo_id,
            filename="voices.json",
            local_files_only=True,
        )
        return path is not None and os.path.exists(path)
    except Exception:
        return False


# ── Backend Selection ────────────────────────────────────────────────────────

def select_backend(
    backbone: BackboneConfig,
    codec: CodecConfig,
    device: str,
    force_lmdeploy: bool = False,
) -> str:
    """Decide which backend class name to use."""
    is_gguf = backbone.is_gguf
    is_turbo = "turbo" in backbone.display_name.lower()

    if is_gguf and device == "cuda":
        return "turbo_gpu"
    if is_gguf:
        return "turbo"
    if is_turbo and device == "cuda":
        return "turbo_gpu"
    if is_turbo:
        return "turbo"
    if device == "xpu":
        return "xpu"
    if force_lmdeploy and device == "cuda" and not is_gguf:
        return "fast"
    return "standard"


def resolve_devices(backbone: BackboneConfig, codec: CodecConfig, device: str) -> tuple[str, str]:
    """Resolve backbone_device and codec_device strings."""
    if backbone.is_gguf:
        bd = "gpu" if device == "cuda" else "cpu"
    elif device == "xpu":
        bd = "xpu"
    elif device == "mps":
        bd = "mps"
    elif device == "cuda":
        bd = "cuda"
    else:
        bd = "cpu"

    if codec.is_onnx:
        cd = "cpu"
    elif device in ("cuda", "mps", "xpu"):
        cd = device
    else:
        cd = "cpu"

    return bd, cd


# ── Model Manager ────────────────────────────────────────────────────────────

class ModelLoadError(Exception):
    """Raised when model loading fails."""
    pass


class ModelManager:
    """
    Manages the TTS model lifecycle with:
    - Single-load locking
    - Cache-first loading
    - Progress callbacks for UI updates
    - Thread-safe state
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @property
    def is_loading(self) -> bool:
        return getattr(self, "_loading", False)

    def load(
        self,
        backbone_key: str,
        codec_key: str,
        device: str,
        force_lmdeploy: bool = False,
        hf_token: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Any:
        """Load the TTS model. Blocks until complete."""
        if device == "auto":
            resolved_device, _ = detect_device()
        else:
            resolved_device = device

        backbone_cfg = AVAILABLE_BACKBONES.get(backbone_key)
        codec_cfg = AVAILABLE_CODECS.get(codec_key)

        if backbone_cfg is None:
            raise ModelLoadError(f"Unknown backbone: {backbone_key}")
        if codec_cfg is None:
            raise ModelLoadError(f"Unknown codec: {codec_key}")

        # GPU gate: v2 (Local) - works with any device
        if backbone_key == "phuonganh-tts-v2 (Local)" and resolved_device not in ("cuda", "mps", "xpu", "cpu"):
            raise ModelLoadError(
                "phuonganh-tts-v2 cần CPU/GPU để chạy. "
                "Vui lòng kiểm tra thiết bị của bạn."
            )

        backend_type = select_backend(backbone_cfg, codec_cfg, resolved_device, force_lmdeploy)
        backbone_device, codec_device = resolve_devices(backbone_cfg, codec_cfg, resolved_device)

        def report(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        report(f"⏳ Đang tải model: {backbone_cfg.display_name}")

        cache_ok = is_model_cached(backbone_cfg.repo_id, backbone_cfg.gguf_filename)
        voices_ok = is_voices_json_cached(backbone_cfg.repo_id)
        codec_cache_ok = is_model_cached(codec_cfg.repo_id)

        _offline_forced = False
        try:
            # Auto-detect offline mode: if everything is cached, switch to offline
            _was_offline = os.environ.get("HF_HUB_OFFLINE") == "1"
            if cache_ok and voices_ok and codec_cache_ok and not _was_offline:
                os.environ["HF_HUB_OFFLINE"] = "1"
                _offline_forced = True
                report("📦 Tất cả đã có sẵn trong cache cục bộ — bật chế độ offline.")
            elif cache_ok and voices_ok and codec_cache_ok:
                report("📦 Tất cả đã có sẵn trong cache cục bộ.")
            elif cache_ok and codec_cache_ok:
                report("📦 Model + codec đã cache, đang tải voices.json...")
            elif cache_ok:
                report("📦 Model đã cache, đang tải codec lần đầu...")
                _pre_download_codec(codec_cfg, report)
                report("✅ Codec đã được cache.")
            else:
                report("📥 Đang tải model lần đầu (sẽ được cache cho lần sau)...")
                _pre_download_codec(codec_cfg, report)
                report("✅ Codec đã được cache.")

            tts = self._do_load(
                backbone_cfg=backbone_cfg,
                codec_cfg=codec_cfg,
                backend_type=backend_type,
                backbone_device=backbone_device,
                codec_device=codec_device,
                force_lmdeploy=force_lmdeploy,
                hf_token=hf_token,
                report=report,
            )
            report("✅ Model đã tải thành công!")
            return tts, backend_type, backbone_device, codec_device

        except Exception as e:
            logger.error(f"Model load failed: {e}")
            raise ModelLoadError(str(e)) from e

        finally:
            if _offline_forced:
                os.environ.pop("HF_HUB_OFFLINE", None)

    def _do_load(
        self,
        backbone_cfg: BackboneConfig,
        codec_cfg: CodecConfig,
        backend_type: str,
        backbone_device: str,
        codec_device: str,
        force_lmdeploy: bool,
        hf_token: Optional[str],
        report: Callable[[str], None],
    ) -> Any:
        """Internal load implementation using phuonganh_tts."""
        from phuonganh_tts import PhuongAnh

        report("🔧 Khởi tạo engine...")
        kwargs: dict[str, Any] = {
            "backbone_repo": backbone_cfg.repo_id,
            "codec_repo": codec_cfg.repo_id,
            "hf_token": hf_token,
        }

        if backbone_cfg.gguf_filename:
            kwargs["gguf_filename"] = backbone_cfg.gguf_filename

        if backend_type in ("turbo", "turbo_gpu"):
            kwargs["mode"] = backend_type
            kwargs["device"] = backbone_device
        elif backend_type == "fast":
            kwargs["mode"] = "fast"
        elif backend_type == "xpu":
            kwargs["mode"] = "xpu"
        else:
            kwargs["mode"] = "standard"
            kwargs["backbone_device"] = backbone_device
            kwargs["codec_device"] = codec_device

        tts = PhuongAnh(**kwargs)
        return tts


# Global singleton
_model_manager: Optional[ModelManager] = None
_manager_lock = threading.Lock()


def get_model_manager() -> ModelManager:
    global _model_manager
    with _manager_lock:
        if _model_manager is None:
            _model_manager = ModelManager()
        return _model_manager
