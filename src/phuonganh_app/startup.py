"""
Startup orchestration for phuonganh-tts.

Handles the auto-load sequence on application start:
1. Detect hardware
2. Select default model (phuonganh-tts-v2 local)
3. Check cache
4. Load model
5. Populate voice list
6. Report ready state to UI state
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from phuonganh_app.model_manager import (
    ModelManager,
    get_model_manager,
    AVAILABLE_BACKBONES,
    AVAILABLE_CODECS,
)
from phuonganh_app.tts_engine import TTSEngine
from phuonganh_app.ui_state import (
    UIState,
    get_ui_state,
    ModelStatus,
    VoicePreset,
)

logger = logging.getLogger("phuonganh.startup")


class StartupError(Exception):
    """Raised when startup fails."""
    pass


def auto_start(
    progress_callback: Optional[Callable[[str], None]] = None,
    hf_token: Optional[str] = None,
) -> TTSEngine:
    """
    Automatically load the default model (phuonganh-tts-v2 local).

    This is the single entry point for startup model loading.
    """
    state = get_ui_state()
    manager = get_model_manager()
    state.set_model_status(ModelStatus.LOADING)

    def report(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    try:
        from phuonganh_app.model_manager import detect_device, has_gpu, is_model_cached
        device, _ = detect_device()

        report(f"🖥️  Thiết bị phát hiện: {device.upper()}")

        if not has_gpu():
            report("⚠️  Không tìm thấy GPU. Sử dụng phiên bản CPU.")
            backbone_key = "phuonganh-tts-v2 (Local)"
            codec_key = "NeuCodec (ONNX)"
            use_lmdeploy = False
        else:
            report("✅ GPU được phát hiện. Sử dụng phuonganh-tts-v2 (Local) với GPU.")
            backbone_key = "phuonganh-tts-v2 (Local)"
            codec_key = "NeuCodec (ONNX)"
            use_lmdeploy = False

        backbone_cfg = AVAILABLE_BACKBONES[backbone_key]
        codec_cfg = AVAILABLE_CODECS[codec_key]

        cache_ok = is_model_cached(backbone_cfg.repo_id, backbone_cfg.gguf_filename)
        voices_ok = is_model_cached(backbone_cfg.repo_id, "voices.json")

        if cache_ok and voices_ok:
            report("💾 Model đã có trong cache. Không cần tải lại.")
        elif cache_ok:
            report("💾 Model đã cache, đang tải voices.json...")
        else:
            report("📥 Model chưa có trong cache. Đang tải lần đầu...")

        report("⏳ Đang khởi tạo model. Vui lòng chờ...")

        tts, backend_type, backbone_device, codec_device = manager.load(
            backbone_key=backbone_key,
            codec_key=codec_key,
            device=device,
            force_lmdeploy=use_lmdeploy,
            hf_token=hf_token,
            progress_callback=report,
        )

        engine = TTSEngine(tts, mode=backend_type)
        _load_voices(state, engine)

        stats = engine.get_optimization_stats()
        state.set_optimization_stats(
            triton_enabled=stats.get("triton_enabled", False),
            max_batch_size=stats.get("max_batch_size", 4),
            cached_references=stats.get("cached_references", 0),
        )

        state.set_model_status(
            status=ModelStatus.LOADED,
            tts_instance=engine,
            backbone_name=backbone_key,
            backbone_repo=backbone_cfg.repo_id,
            codec_name=codec_key,
            codec_repo=codec_cfg.repo_id,
            backend_type=backend_type,
            device_name=backbone_device,
        )

        report("✅ phuonganh-tts đã sẵn sàng!")
        return engine

    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        state.set_model_status(
            status=ModelStatus.FAILED,
            error_message=str(e),
        )
        raise StartupError(str(e)) from e


def _load_voices(state: UIState, engine: TTSEngine) -> None:
    """Populate the UI state with voice presets from the loaded model."""
    try:
        raw_voices = engine.list_preset_voices()
    except Exception as e:
        logger.warning(f"Could not load preset voices: {e}")
        raw_voices = []

    preset_map: dict = {}
    default_id = engine.get_default_voice_id()

    for item in raw_voices:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            desc, voice_id = item[0], item[1]
        else:
            desc = voice_id = str(item)

        try:
            voice_data = engine.get_preset_voice(voice_id)
            preset_map[voice_id] = VoicePreset.from_dict(voice_id, voice_data)
        except Exception:
            preset_map[voice_id] = VoicePreset(
                id=voice_id,
                description=desc,
                codes=None,
                text="",
                podcast_enabled=True,
            )

    state.set_voices(default_voice_id=default_id, preset_voices=preset_map)


def start_in_background(
    on_ready: Callable[[TTSEngine], None],
    on_error: Callable[[Exception], None],
    hf_token: Optional[str] = None,
) -> None:
    """Start the model loading in a background thread."""

    def bg_task():
        try:
            engine = auto_start(hf_token=hf_token)
            on_ready(engine)
        except Exception as e:
            on_error(e)

    t = threading.Thread(target=bg_task, daemon=True, name="phuonganh-startup")
    t.start()
