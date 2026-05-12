"""
TTS engine wrapper for phuonganh-tts.
Thin, stable wrapper around phuonganh_tts backends.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

logger = logging.getLogger("phuonganh.tts_engine")


def build_engine(
    mode: str,
    backbone_repo: str,
    codec_repo: str,
    backbone_device: str,
    codec_device: str,
    gguf_filename: Optional[str] = None,
    hf_token: Optional[str] = None,
    force_lmdeploy: bool = False,
) -> "TTSEngine":
    """Build and return the appropriate TTS engine instance."""
    from phuonganh_tts import PhuongAnh

    kwargs: Dict[str, Any] = {
        "backbone_repo": backbone_repo,
        "codec_repo": codec_repo,
        "hf_token": hf_token,
    }

    if gguf_filename:
        kwargs["gguf_filename"] = gguf_filename

    if mode in ("turbo", "turbo_gpu"):
        kwargs["mode"] = mode
        kwargs["device"] = backbone_device
        if mode == "turbo_gpu" and force_lmdeploy:
            kwargs["backend"] = "lmdeploy"
    elif mode == "fast":
        kwargs["mode"] = "fast"
    else:
        kwargs["mode"] = "standard"
        kwargs["backbone_device"] = backbone_device
        kwargs["codec_device"] = codec_device

    logger.info(f"Building engine: mode={mode}, backbone={backbone_repo}, device={backbone_device}")
    tts = PhuongAnh(**kwargs)
    return TTSEngine(tts, mode=mode)


class TTSEngine:
    """
    Unified wrapper around phuonganh_tts TTS backends.
    Provides a stable API surface for the UI handlers.
    """

    def __init__(self, backend: Any, mode: str) -> None:
        self._backend = backend
        self._mode = mode
        self._lora_loaded = False
        self._current_lora_repo: Optional[str] = None

    @property
    def backend_type(self) -> str:
        return self._mode

    @property
    def is_lmdeploy(self) -> bool:
        return self._mode == "fast"

    # ── Voice Management ─────────────────────────────────────────────────────

    def list_preset_voices(self) -> List[tuple]:
        return self._backend.list_preset_voices()

    def get_preset_voice(self, voice_id: str) -> Dict[str, Any]:
        return self._backend.get_preset_voice(voice_id)

    def get_default_voice_id(self) -> str:
        return getattr(self._backend, "_default_voice", "") or ""

    def encode_reference(self, audio_path: Union[str, Path]) -> np.ndarray:
        return self._backend.encode_reference(audio_path)

    # ── Inference ─────────────────────────────────────────────────────────────

    def infer(
        self,
        text: str,
        voice_id: Optional[str] = None,
        ref_codes: Optional[Any] = None,
        ref_text: Optional[str] = None,
        temperature: float = 0.7,
        max_chars: int = 256,
        emotion_tag: Optional[str] = None,
        skip_normalize: bool = False,
    ) -> np.ndarray:
        if voice_id and not ref_codes:
            voice_data = self.get_preset_voice(voice_id)
            ref_codes = voice_data.get("codes")
            ref_text = voice_data.get("text", "")

        if hasattr(ref_codes, "cpu"):
            ref_codes = ref_codes.cpu().numpy()

        return self._backend.infer(
            text,
            ref_codes=ref_codes,
            ref_text=ref_text,
            temperature=temperature,
            max_chars=max_chars,
            skip_normalize=skip_normalize,
            emotion_tag=emotion_tag,
        )

    def infer_batch(
        self,
        texts: List[str],
        ref_codes: Optional[Any],
        ref_text: Optional[str],
        temperature: float = 0.7,
        max_batch_size: int = 4,
        skip_normalize: bool = False,
    ) -> List[np.ndarray]:
        if hasattr(ref_codes, "cpu"):
            ref_codes = ref_codes.cpu().numpy()
        return self._backend.infer_batch(
            texts,
            ref_codes=ref_codes,
            ref_text=ref_text,
            temperature=temperature,
            max_batch_size=max_batch_size,
            skip_normalize=skip_normalize,
        )

    def infer_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        ref_codes: Optional[Any] = None,
        ref_text: Optional[str] = None,
        temperature: float = 0.7,
        max_chars: int = 256,
        emotion_tag: Optional[str] = None,
    ):
        if voice_id and not ref_codes:
            voice_data = self.get_preset_voice(voice_id)
            ref_codes = voice_data.get("codes")
            ref_text = voice_data.get("text", "")

        if hasattr(ref_codes, "cpu"):
            ref_codes = ref_codes.cpu().numpy()

        yield from self._backend.infer_stream(
            text,
            ref_codes=ref_codes,
            ref_text=ref_text,
            temperature=temperature,
            max_chars=max_chars,
            skip_normalize=True,
            emotion_tag=emotion_tag,
        )

    # ── LoRA ─────────────────────────────────────────────────────────────────

    def load_lora(
        self,
        lora_repo_id: str,
        base_model_key: Optional[str] = None,
        hf_token: Optional[str] = None,
    ) -> None:
        try:
            self._backend.load_lora_adapter(lora_repo_id, hf_token=hf_token)
            if hasattr(self._backend.backbone, "merge_and_unload"):
                self._backend.backbone = self._backend.backbone.merge_and_unload()
            self._lora_loaded = True
            self._current_lora_repo = lora_repo_id
            logger.info(f"LoRA merged: {lora_repo_id}")
        except NotImplementedError:
            logger.warning("This backend does not support LoRA merging.")
            raise
        except Exception as e:
            logger.error(f"LoRA merge failed: {e}")
            raise

    # ── Optimization Stats ───────────────────────────────────────────────────

    def get_optimization_stats(self) -> Dict[str, Any]:
        if self.is_lmdeploy and hasattr(self._backend, "get_optimization_stats"):
            return self._backend.get_optimization_stats()
        return {
            "triton_enabled": False,
            "max_batch_size": 4,
            "cached_references": 0,
            "prefix_caching": False,
        }

    # ── Memory ──────────────────────────────────────────────────────────────

    def cleanup_memory(self) -> None:
        if self.is_lmdeploy and hasattr(self._backend, "cleanup_memory"):
            self._backend.cleanup_memory()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        if hasattr(self._backend, "close"):
            self._backend.close()
        self._backend = None

    def __enter__(self) -> "TTSEngine":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
