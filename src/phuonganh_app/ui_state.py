"""
UI state management for phuonganh-tts.
No global mutable state — everything is encapsulated in a singleton class.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np


class ModelStatus(str, Enum):
    """Possible states for the model lifecycle."""
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


class GenerationMode(str, Enum):
    """Synthesis mode."""
    STANDARD = "standard"


@dataclass
class VoicePreset:
    """A voice preset with its reference data."""
    id: str
    description: str
    codes: Any
    text: str
    podcast_enabled: bool = True

    @classmethod
    def from_dict(cls, voice_id: str, data: dict) -> "VoicePreset":
        codes = data.get("codes", [])
        if isinstance(codes, list) and codes:
            if isinstance(codes[0], float):
                codes = np.array(codes, dtype=np.float32)
            else:
                import torch as _torch
                codes = _torch.tensor(codes, dtype=_torch.long)
        podcast = data.get("podcast", True)
        if isinstance(podcast, str):
            podcast = podcast.strip().lower() == "true"
        return cls(
            id=voice_id,
            description=data.get("description", voice_id),
            codes=codes,
            text=data.get("text", ""),
            podcast_enabled=bool(podcast),
        )


@dataclass
class UserInfo:
    """Logged-in user information."""
    id: str
    email: str
    username: Optional[str] = None
    subscription_plan: str = "free"
    is_verified: bool = False
    role: str = "user"  # Added for admin role support

    @classmethod
    def from_dict(cls, data: dict) -> "UserInfo":
        """Create UserInfo from a dictionary (e.g., from API response)."""
        return cls(
            id=data.get("id", ""),
            email=data.get("email", ""),
            username=data.get("username"),
            subscription_plan=data.get("subscription_plan", "free"),
            is_verified=data.get("is_verified", False),
            role=data.get("role", "user"),
        )

    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == "admin"


@dataclass
class TTSState:
    """Immutable-ish snapshot of the TTS engine state."""
    status: ModelStatus = ModelStatus.NOT_LOADED
    error_message: Optional[str] = None
    tts_instance: Any = None
    backbone_name: str = ""
    backbone_repo: str = ""
    codec_name: str = ""
    codec_repo: str = ""
    backend_type: str = ""
    device_name: str = ""
    default_voice_id: str = ""
    preset_voices: dict = field(default_factory=dict)
    conversation_voices: list = field(default_factory=list)
    triton_enabled: bool = False
    max_batch_size: int = 4
    cached_references: int = 0
    generation_mode: GenerationMode = GenerationMode.STANDARD
    user: Optional[UserInfo] = None

    def is_ready(self) -> bool:
        return self.status == ModelStatus.LOADED and self.tts_instance is not None

    def status_message(self) -> str:
        if self.status == ModelStatus.NOT_LOADED:
            return "⏳ Model chưa được tải."
        if self.status == ModelStatus.LOADING:
            return "⏳ Đang tải model..."
        if self.status == ModelStatus.FAILED:
            return f"❌ Lỗi: {self.error_message or 'Không xác định'}"
        if self.status == ModelStatus.LOADED:
            backend = self._backend_label()
            lines = [
                "✅ phuonganh-tts đã sẵn sàng!",
                "",
                f"🔧 Backend: {backend}",
                f"🦜 Model: {self.backbone_name}",
                f"🎵 Codec: {self.codec_name}",
                f"🖥️ Thiết bị: {self.device_name}",
            ]
            if self.backend_type == "fast":
                lines.append(f"🔧 Triton: {'✅' if self.triton_enabled else '❌'}")
                lines.append(f"📦 Batch Size: {self.max_batch_size}")
            return "\n".join(lines)
        return "⏳ Trạng thái không xác định."

    def _backend_label(self) -> str:
        if self.backend_type == "fast":
            return "🚀 LMDeploy (Tối ưu)"
        if self.backend_type in ("turbo", "turbo_gpu"):
            return "⚡ Turbo"
        if self.backend_type == "xpu":
            return "🟣 Intel XPU"
        return "📦 Standard"


class UIState:
    """
    Thread-safe singleton holding all application state.
    Replaces module-level globals from the old gradio_main.py.
    """
    _instance: Optional["UIState"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "UIState":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._state = TTSState()
                cls._instance._state_lock = threading.RLock()
                cls._instance._preset_cache: list = []
                cls._instance._conv_cache: list = []
            return cls._instance

    def get_state(self) -> TTSState:
        with self._state_lock:
            s = self._state
            return TTSState(
                status=s.status,
                error_message=s.error_message,
                tts_instance=s.tts_instance,
                backbone_name=s.backbone_name,
                backbone_repo=s.backbone_repo,
                codec_name=s.codec_name,
                codec_repo=s.codec_repo,
                backend_type=s.backend_type,
                device_name=s.device_name,
                default_voice_id=s.default_voice_id,
                preset_voices=dict(s.preset_voices),
                conversation_voices=list(s.conversation_voices),
                triton_enabled=s.triton_enabled,
                max_batch_size=s.max_batch_size,
                cached_references=s.cached_references,
                generation_mode=s.generation_mode,
                user=s.user,
            )

    def set_model_status(
        self,
        status: ModelStatus,
        tts_instance: Any = None,
        backbone_name: str = "",
        backbone_repo: str = "",
        codec_name: str = "",
        codec_repo: str = "",
        backend_type: str = "",
        device_name: str = "",
        error_message: Optional[str] = None,
    ) -> None:
        with self._state_lock:
            self._state.status = status
            self._state.tts_instance = tts_instance
            self._state.backbone_name = backbone_name
            self._state.backbone_repo = backbone_repo
            self._state.codec_name = codec_name
            self._state.codec_repo = codec_repo
            self._state.backend_type = backend_type
            self._state.device_name = device_name
            self._state.error_message = error_message

    def set_voices(self, default_voice_id: str, preset_voices: dict) -> None:
        with self._state_lock:
            self._state.default_voice_id = default_voice_id
            self._state.preset_voices = preset_voices
            self._preset_cache = [(v.description, v.id) for v in preset_voices.values()]
            self._conv_cache = [
                (v.description, v.id)
                for v in preset_voices.values()
                if v.podcast_enabled
            ]
            self._state.conversation_voices = list(self._conv_cache)

    def set_optimization_stats(
        self,
        triton_enabled: bool,
        max_batch_size: int,
        cached_references: int,
    ) -> None:
        with self._state_lock:
            self._state.triton_enabled = triton_enabled
            self._state.max_batch_size = max_batch_size
            self._state.cached_references = cached_references

    def get_preset_voices(self) -> list:
        with self._state_lock:
            return list(self._preset_cache)

    def get_conversation_voices(self) -> list:
        with self._state_lock:
            return list(self._conv_cache)

    def get_default_voice_id(self) -> str:
        with self._state_lock:
            return self._state.default_voice_id

    def get_tts_instance(self) -> Any:
        with self._state_lock:
            return self._state.tts_instance

    def reset(self) -> None:
        with self._state_lock:
            self._state = TTSState()
            self._preset_cache = []
            self._conv_cache = []

    def set_user(self, user: Optional[UserInfo]) -> None:
        """Set the current logged-in user."""
        with self._state_lock:
            self._state.user = user

    def get_user(self) -> Optional[UserInfo]:
        """Get the current logged-in user."""
        with self._state_lock:
            return self._state.user

    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        with self._state_lock:
            return self._state.user is not None

    def clear_user(self) -> None:
        """Clear the current logged-in user (logout)."""
        with self._state_lock:
            self._state.user = None


def get_ui_state() -> UIState:
    return UIState()
