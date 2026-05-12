"""
phuonganh_app — phuonganh-tts Gradio Application Package

Provides the web UI and model lifecycle management.
"""
from phuonganh_app.ui_state import (
    get_ui_state,
    UIState,
    TTSState,
    VoicePreset,
    ModelStatus,
    GenerationMode,
)
from phuonganh_app.model_manager import (
    AVAILABLE_BACKBONES,
    AVAILABLE_CODECS,
    detect_device,
    has_gpu,
    ModelLoadError,
    get_model_manager,
)
from phuonganh_app.startup import (
    auto_start,
    start_in_background,
    StartupError,
)

__all__ = [
    "get_ui_state",
    "UIState",
    "TTSState",
    "VoicePreset",
    "ModelStatus",
    "GenerationMode",
    "AVAILABLE_BACKBONES",
    "AVAILABLE_CODECS",
    "detect_device",
    "has_gpu",
    "ModelLoadError",
    "get_model_manager",
    "auto_start",
    "start_in_background",
    "StartupError",
]
