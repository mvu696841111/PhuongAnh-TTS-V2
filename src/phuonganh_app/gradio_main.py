"""
phuonganh-tts — Polished Gradio Application

A production-grade Vietnamese TTS web UI with:
- Auto-load on startup (phuonganh-tts-v2 local)
- User authentication (login/register)
- Sidebar with model info and GPU status
- Generation history panel
- Loading overlay
- Clean, standalone product feel
"""
from __future__ import annotations

import gc
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

# Force offline mode if local model exists
_local_model_path = Path(__file__).parent.parent.parent / "models" / "phuonganh-tts-v2"
if _local_model_path.exists():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

import gradio as gr
import numpy as np
import soundfile as sf

from phuonganh_app import (
    get_ui_state,
    AVAILABLE_BACKBONES,
    AVAILABLE_CODECS,
    has_gpu,
    detect_device,
    ModelStatus,
    VoicePreset,
)
from phuonganh_app.model_manager import (
    ModelLoadError,
    get_model_manager,
)
from phuonganh_app.auth_service import (
    get_auth_service,
    AuthUser,
)


# ── Constants ─────────────────────────────────────────────────────
APP_NAME = "phuonganh-tts"
APP_TITLE = "phuonganh-tts Studio"
DEFAULT_TEXT = (
    "Hà Nội, trái tim của Việt Nam, là một thành phố ngàn năm văn hiến "
    "với bề dày lịch sử và văn hóa độc động. "
    "Bước chân trên những con phố cổ kính quanh Hồ Hoàn Kiếm, "
    "du khách như được du hành ngược thời gian."
)
MAX_SPEAKERS = 8
_HISTORY_LIMIT = 20
_STOP = threading.Event()


# ── Theme & CSS ─────────────────────────────────────────────────

theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="cyan",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui"],
).set(
    button_primary_background_fill="linear-gradient(90deg, #6366f1 0%, #0ea5e9 100%)",
    button_primary_background_fill_hover="linear-gradient(90deg, #4f46e5 0%, #0284c7 100%)",
)

css = """
.container { max-width: 1200px; margin: auto; }
.sidebar { min-width: 280px; max-width: 320px; }
.header-box {
    text-align: center;
    margin-bottom: 16px;
    padding: 16px;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    border-radius: 12px;
}
.header-title { font-size: 2rem; font-weight: 800; color: white !important; }
.gradient-text {
    background: -webkit-linear-gradient(45deg, #60A5FA, #22D3EE);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.model-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 12px;
    margin-bottom: 12px;
}
.model-card-title { font-weight: 600; color: #e2e8f0; font-size: 0.9rem; }
.model-card-row { display: flex; justify-content: space-between; color: #94a3b8; font-size: 0.8rem; padding: 2px 0; }
.gpu-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.gpu-on { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
.gpu-off { background: #ef4444; }
.history-item {
    background: #1e293b;
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 0.8rem;
    cursor: pointer;
}
.history-item:hover { background: #334155; }
.loading-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(15, 23, 42, 0.92);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    z-index: 1000; border-radius: 0;
}
.loading-title { color: white; font-size: 1.5rem; font-weight: 700; margin-bottom: 8px; }
.loading-sub { color: #94a3b8; font-size: 0.9rem; margin-bottom: 24px; }
.spinner {
    width: 48px; height: 48px; border: 4px solid #334155;
    border-top-color: #60A5FA; border-radius: 50%;
    animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
"""

head_html = (
    '<link rel="icon" href="data:image/svg+xml,'
    '<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22>'
    '<text y=%22.9em%22 font-size=%2290%22>🦜</text></svg>">'
)


# ── Helpers ─────────────────────────────────────────────────────

def _cleanup_gpu() -> None:
    if "torch" in sys.modules:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    gc.collect()


def _resolve_voice_id(voice_id: str, voices: list) -> str:
    if not voice_id or not voices:
        return voice_id
    for item in voices:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            if voice_id in item:
                return item[1]
        elif voice_id == item:
            return item
    return voice_id


def _gpu_status_html() -> str:
    """Return HTML for the GPU status indicator in the sidebar."""
    device, device_str = detect_device()
    has_g = has_gpu()
    gpu_class = "gpu-on" if has_g else "gpu-off"
    gpu_label = device.upper() if has_g else "CPU"
    return (
        f'<span class="gpu-indicator {gpu_class}"></span>'
        f'<b>{gpu_label}</b>'
    )


# ── Auth State ────────────────────────────────────────────────────

_auth_service = get_auth_service()


def _user_status_html() -> str:
    """Return HTML for user status in sidebar."""
    if _auth_service.is_authenticated():
        user = _auth_service.user
        plan_display = _auth_service.get_plan_display_name(user.subscription_plan)
        return (
            f'<div style="background:#1e293b; border:1px solid #22c55e; border-radius:8px; padding:10px 14px; margin-bottom:12px;">'
            f'<div style="color:#22c55e; font-size:0.75rem;">✅ Đã đăng nhập</div>'
            f'<div style="color:#e2e8f0; font-size:0.85rem; margin-top:4px;">📧 {user.email}</div>'
            f'<div style="color:#94a3b8; font-size:0.7rem; margin-top:2px;">🎫 {plan_display}</div>'
            f'</div>'
        )
    else:
        return (
            f'<div style="background:#1e293b; border:1px solid #f59e0b; border-radius:8px; padding:10px 14px; margin-bottom:12px;">'
            f'<div style="color:#f59e0b; font-size:0.75rem;">⚠️ Chưa đăng nhập</div>'
            f'<div style="color:#94a3b8; font-size:0.7rem; margin-top:4px;">Sử dụng miễn phí với giới hạn</div>'
            f'</div>'
        )


def _model_card_html(state_snapshot) -> str:
    """Build the model info card HTML for the sidebar."""
    if state_snapshot.is_ready():
        rows = [
            ("Model", state_snapshot.backbone_name or "—"),
            ("Backend", state_snapshot.backend_type or "—"),
            ("Device", state_snapshot.device_name or "—"),
            ("Codec", state_snapshot.codec_name or "—"),
        ]
        if state_snapshot.backend_type == "fast":
            rows.append(("Triton", "✅" if state_snapshot.triton_enabled else "❌"))
            rows.append(("Batch", str(state_snapshot.max_batch_size)))
        rows_html = "\n".join(
            f'<div class="model-card-row"><span>{k}</span><span>{v}</span></div>'
            for k, v in rows
        )
        return (
            '<div class="model-card">'
            '<div class="model-card-title">📋 Model Info</div>'
            f'{rows_html}'
            '</div>'
        )
    elif state_snapshot.status == ModelStatus.LOADING:
        return '<div class="model-card"><div class="model-card-title">⏳ Đang tải model...</div></div>'
    elif state_snapshot.status == ModelStatus.FAILED:
        return f'<div class="model-card"><div class="model-card-title">❌ Lỗi</div><div class="model-card-row"><span>Chi tiết</span><span>{state_snapshot.error_message or "—"}</span></div></div>'
    else:
        return '<div class="model-card"><div class="model-card-title">⏳ Model chưa tải</div></div>'


# ── Authentication Handlers ───────────────────────────────────────

def handle_login(email: str, password: str):
    """Handle user login with role support."""
    try:
        if not email or not email.strip():
            yield (
                "❌ Vui lòng nhập email.",
                gr.update(),
                gr.update(visible=True),
                gr.update(visible=False),
            )
            return

        if not password:
            yield (
                "❌ Vui lòng nhập mật khẩu.",
                gr.update(),
                gr.update(visible=True),
                gr.update(visible=False),
            )
            return

        user = _auth_service.login(email.strip(), password)

        # Get role from user object
        user_role = getattr(user, 'role', 'user')

        # Update UI state with role support
        from phuonganh_app.ui_state import UserInfo
        get_ui_state().set_user(UserInfo(
            id=user.id,
            email=user.email,
            username=user.username,
            subscription_plan=user.subscription_plan,
            is_verified=user.is_verified,
            role=user_role,
        ))

        # Check if admin - show different message
        if user_role == 'admin':
            yield (
                "✅ Đăng nhập Admin thành công! Chuyển hướng đến Dashboard...",
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=True),
            )
        else:
            yield (
                f"✅ Đăng nhập thành công!",
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=True),
            )

    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            error_msg = "Email hoặc mật khẩu không đúng."
        yield (
            f"❌ Đăng nhập thất bại: {error_msg}",
            gr.update(),
            gr.update(visible=True),
            gr.update(visible=False),
        )


def handle_register(email: str, password: str, confirm_password: str, username: str):
    """Handle user registration."""
    try:
        if not email or not email.strip():
            yield (
                "❌ Vui lòng nhập email.",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if not password:
            yield (
                "❌ Vui lòng nhập mật khẩu.",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if len(password) < 8:
            yield (
                "❌ Mật khẩu phải có ít nhất 8 ký tự.",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if not any(c.isupper() for c in password):
            yield (
                "❌ Mật khẩu phải có ít nhất 1 chữ hoa (A-Z).",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if not any(c.islower() for c in password):
            yield (
                "❌ Mật khẩu phải có ít nhất 1 chữ thường (a-z).",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if not any(c.isdigit() for c in password):
            yield (
                "❌ Mật khẩu phải có ít nhất 1 số (0-9).",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        if password != confirm_password:
            yield (
                "❌ Mật khẩu xác nhận không khớp.",
                gr.update(),
                gr.update(),
                gr.update(),
            )
            return

        user = _auth_service.register(
            email=email.strip(),
            password=password,
            username=username.strip() if username else None,
        )

        # Auto login after registration
        _auth_service.login(email.strip(), password)

        # Update UI state
        from phuonganh_app.ui_state import UserInfo
        get_ui_state().set_user(UserInfo(
            id=user.id,
            email=user.email,
            username=user.username,
            subscription_plan=user.subscription_plan,
            is_verified=user.is_verified,
        ))

        yield (
            f"✅ Đăng ký thành công! Vui lòng đăng nhập.",
            gr.update(),
            gr.update(),
            gr.update(),
        )

    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            error_msg = "Email này đã được đăng ký."
        yield (
            f"❌ Đăng ký thất bại: {error_msg}",
            gr.update(),
            gr.update(),
            gr.update(),
        )


def handle_logout():
    """Handle user logout."""
    _auth_service.logout()
    get_ui_state().clear_user()
    return (
        "✅ Đã đăng xuất.",
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
    )


def check_backend_status():
    """Check if backend is available."""
    if _auth_service.is_backend_available():
        return gr.update(visible=True)
    else:
        return gr.update(visible=False)


def update_sidebar_auth():
    """Update sidebar with current auth state."""
    user_html = _user_status_html()
    state = get_ui_state()
    s = state.get_state()
    gpu_html = _gpu_status_html()
    card_html = _model_card_html(s)

    # Update login button visibility
    if _auth_service.is_authenticated():
        login_btn = gr.update(visible=False)
        logout_btn = gr.update(visible=True)
        auth_status = gr.update(value=user_html, visible=True)
    else:
        login_btn = gr.update(visible=True)
        logout_btn = gr.update(visible=False)
        auth_status = gr.update(value=user_html, visible=True)

    return auth_status, gpu_html, card_html, login_btn, logout_btn


# ── Model Loading Handler ──────────────────────────────────────

def load_model(
    backbone_choice: str,
    codec_choice: str,
    device_choice: str,
    force_lmdeploy: bool,
    custom_model_id: str,
    custom_base_model: str,
    hf_token: str,
):
    """Generator: loads the model and yields UI state tuples."""
    state = get_ui_state()
    manager = get_model_manager()
    state.set_model_status(ModelStatus.LOADING)

    # Resolve config
    backbone_key = backbone_choice
    codec_key = codec_choice

    if backbone_choice == "Custom Model":
        if not custom_model_id or not custom_model_id.strip():
            yield (
                "❌ Vui lòng nhập Model ID.",
                gr.update(interactive=False),
                gr.update(interactive=True),
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                gr.update(),
            )
            return

        from phuonganh_app.model_manager import BackboneConfig
        is_gguf = "gguf" in custom_model_id.lower()
        backbone_cfg = BackboneConfig(
            display_name=custom_model_id,
            repo_id=custom_model_id.strip(),
            supports_streaming=False,
            is_gguf=is_gguf,
        )
        AVAILABLE_BACKBONES[custom_model_id] = backbone_cfg
        backbone_key = custom_model_id

    if backbone_key not in AVAILABLE_BACKBONES:
        yield (
            f"❌ Backbone không hợp lệ: {backbone_key}",
            gr.update(interactive=False),
            gr.update(interactive=True),
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            gr.update(),
        )
        return

    backbone_cfg = AVAILABLE_BACKBONES[backbone_key]
    codec_cfg = AVAILABLE_CODECS.get(codec_key, list(AVAILABLE_CODECS.values())[0])

    # Initial yield (loading state)
    yield (
        f"⏳ Đang tải {backbone_cfg.display_name}...",
        gr.update(interactive=False),
        gr.update(interactive=True),
        gr.update(visible=False),
        gr.update(choices=[], value=None),
        gr.update(),
    )

    # GPU gate - check device compatibility for local model
    device = device_choice if device_choice != "Auto" else detect_device()[0]

    # Load
    try:
        tts, backend_type, backbone_device, codec_device = manager.load(
            backbone_key=backbone_key,
            codec_key=codec_key,
            device=device,
            force_lmdeploy=force_lmdeploy,
            hf_token=hf_token or None,
        )
    except ModelLoadError as e:
        state.set_model_status(
            ModelStatus.FAILED,
            error_message=str(e),
        )
        yield (
            f"❌ Lỗi khi tải model: {e}",
            gr.update(interactive=False),
            gr.update(interactive=True),
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            gr.update(),
        )
        return

    # Load voice presets
    try:
        raw_voices = tts.list_preset_voices()
    except Exception:
        raw_voices = []

    preset_list = []
    conv_list = []
    default_vid = ""

    try:
        default_vid = tts.get_default_voice_id() or ""
    except Exception:
        pass

    for item in raw_voices:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            label, value = item[0], item[1]
        else:
            label = value = str(item)
        preset_list.append((label, value))
        try:
            vdata = tts.get_preset_voice(value)
            podcast = vdata.get("podcast", True)
            if isinstance(podcast, str):
                podcast = podcast.strip().lower() == "true"
            if podcast:
                conv_list.append((label, value))
        except Exception:
            conv_list.append((label, value))

    preset_list.sort(key=lambda x: str(x[0]))
    if not default_vid and preset_list:
        default_vid = preset_list[0][1]

    # Update app state
    state.set_model_status(
        status=ModelStatus.LOADED,
        tts_instance=tts,
        backbone_name=backbone_key,
        backbone_repo=backbone_cfg.repo_id,
        codec_name=codec_key,
        codec_repo=codec_cfg.repo_id,
        backend_type=backend_type,
        device_name=backbone_device,
    )

    preset_map = {}
    for label, value in preset_list:
        try:
            vdata = tts.get_preset_voice(value)
            preset_map[value] = VoicePreset.from_dict(value, vdata)
        except Exception:
            preset_map[value] = VoicePreset(
                id=value, description=label,
                codes=None, text="", podcast_enabled=True,
            )

    state.set_voices(default_voice_id=default_vid, preset_voices=preset_map)

    try:
        stats = tts.get_optimization_stats()
        state.set_optimization_stats(
            triton_enabled=stats.get("triton_enabled", False),
            max_batch_size=stats.get("max_batch_size", 4),
            cached_references=stats.get("cached_references", 0),
        )
    except Exception:
        pass

    # Final success yield
    s = state.get_state()
    is_v2 = backbone_key in ("phuonganh-tts-v2 (Local)", "phuonganh-tts-v2 GGUF (Local)")

    yield (
        s.status_message(),
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(visible=False),
        gr.update(choices=preset_list, value=default_vid, interactive=True),
        gr.update(visible=True),
    )


# ── Synthesis Handler ───────────────────────────────────────────

def synthesize(
    text: str,
    voice_choice: str,
    custom_audio,
    custom_text: str,
    mode_tab: str,
    generation_mode: str,
    use_batch: bool,
    max_batch_size: int,
    temperature: float,
    max_chars: int,
    session_id: str = None,
):
    """Generator: normalize → chunk → infer → join → yield audio."""
    state = get_ui_state()
    _STOP.clear()

    s = state.get_state()
    if not s.is_ready():
        yield None, "⚠️ Model chưa sẵn sàng."
        return

    if not text or not text.strip():
        yield None, "⚠️ Vui lòng nhập văn bản."
        return

    tts = s.tts_instance
    if tts is None:
        yield None, "❌ Model không khả dụng."
        return

    voices = state.get_preset_voices()
    raw_text = text.strip()

    # Load reference
    yield None, "📄 Đang xử lý Reference..."

    try:
        if mode_tab == "preset":
            if not voice_choice or "⚠️" in voice_choice:
                raise ValueError("Vui lòng chọn giọng mẫu.")
            vid = _resolve_voice_id(voice_choice, voices)
            vdata = tts.get_preset_voice(vid)
            ref_codes = vdata.get("codes")
            ref_text = vdata.get("text", "")
        elif mode_tab == "custom":
            if custom_audio is None:
                raise ValueError("Vui lòng upload audio giọng mẫu.")
            ref_text = (custom_text or "").strip()
            ref_codes = tts.encode_reference(custom_audio)
        else:
            raise ValueError(f"Chế độ không hợp lệ: {mode_tab}")

        if hasattr(ref_codes, "cpu"):
            ref_codes = ref_codes.cpu().numpy()

    except Exception as e:
        yield None, f"❌ Lỗi xử lý Reference: {e}"
        return

    # Normalize & chunk
    try:
        from sea_g2p import Normalizer
        normalizer = Normalizer()
        normalized = normalizer.normalize(raw_text)
    except Exception:
        normalized = raw_text

    is_turbo = "turbo" in (s.backend_type or "").lower()

    if is_turbo:
        from phuonganh_utils.phonemize_text import phonemize_with_dict
        from phuonganh_utils.core_utils import split_into_chunks_v2
        phonemes = phonemize_with_dict(normalized, skip_normalize=True)
        chunks = split_into_chunks_v2(phonemes, max_chunk_size=max_chars)
        chunk_texts = [c.text for c in chunks]
    else:
        from phuonganh_utils.core_utils import split_text_into_chunks
        chunk_texts = split_text_into_chunks(normalized, max_chars=max_chars)

    if not chunk_texts:
        yield None, "❌ Không có đoạn văn bản nào để tổng hợp."
        return

    total = len(chunk_texts)
    backend_label = "🚀 LMDeploy" if s.backend_type == "fast" else "📦 Standard"
    yield None, f"🚀 Bắt đầu tổng hợp ({total} đoạn, {backend_label})..."

    all_wavs = []
    sr = 24000
    start_time = time.time()

    try:
        if len(chunk_texts) == 1:
            wav = tts.infer(
                chunk_texts[0], ref_codes=ref_codes, ref_text=ref_text,
                temperature=temperature, max_chars=max_chars, skip_normalize=True,
            )
            all_wavs.append(wav)
        elif use_batch and s.backend_type == "fast" and len(chunk_texts) > 1:
            num_batches = (total + max_batch_size - 1) // max_batch_size
            for i in range(0, total, max_batch_size):
                if _STOP.is_set():
                    yield None, "⏹️ Đã dừng tạo giọng nói."
                    return
                batch_idx = i // max_batch_size
                yield None, f"⚡ Batch {batch_idx+1}/{num_batches}..."
                batch = chunk_texts[i : i + max_batch_size]
                wavs = tts.infer_batch(
                    batch, ref_codes=ref_codes, ref_text=ref_text,
                    temperature=temperature, max_batch_size=max_batch_size,
                    skip_normalize=True,
                )
                all_wavs.extend(wavs)
        else:
            for i, chunk in enumerate(chunk_texts):
                if _STOP.is_set():
                    yield None, "⏹️ Đã dừng tạo giọng nói."
                    return
                yield None, f"⏳ Đang xử lý đoạn {i+1}/{total}..."
                wav = tts.infer(
                    chunk, ref_codes=ref_codes, ref_text=ref_text,
                    temperature=temperature, max_chars=max_chars,
                    skip_normalize=True,
                )
                if wav is not None and len(wav) > 0:
                    all_wavs.append(wav)

        if not all_wavs:
            yield None, "❌ Không sinh được audio nào."
            return

        yield None, "💾 Đang ghép file và lưu..."
        silence_p = 0.0 if is_turbo else 0.15
        from phuonganh_utils.core_utils import join_audio_chunks
        final_wav = join_audio_chunks(all_wavs, sr=sr, silence_p=silence_p)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            sf.write(tmp.name, final_wav, sr)
            out_path = tmp.name

        elapsed = time.time() - start_time
        speed = f" · {len(final_wav)/sr/elapsed:.1f}x realtime" if elapsed > 0 else ""
        yield out_path, f"✅ Hoàn tất! ({elapsed:.1f}s{speed}) [{backend_label}]"

        tts.cleanup_memory()
        _cleanup_gpu()

    except Exception as e:
        import traceback
        traceback.print_exc()
        _cleanup_gpu()
        if "OutOfMemoryError" in type(e).__name__ or "OOM" in str(e):
            yield None, (
                f"❌ GPU hết VRAM! Giảm Batch Size hoặc giảm độ dài văn bản.\n"
                f"Chi tiết: {e}"
            )
        else:
            yield None, f"❌ Lỗi tổng hợp: {e}"


# ── Conversation Handler ─────────────────────────────────────────

def synthesize_conversation(script_text: str, *args):
    """Multi-speaker conversation synthesis."""
    state = get_ui_state()
    _STOP.clear()

    s = state.get_state()
    if not s.is_ready():
        yield None, "⚠️ Model chưa sẵn sàng."
        return

    if not script_text or not script_text.strip():
        yield None, "⚠️ Vui lòng nhập kịch bản hội thoại."
        return

    speaker_names = list(args[:MAX_SPEAKERS])
    speaker_voices = list(args[MAX_SPEAKERS : MAX_SPEAKERS * 2])
    silence_dur = args[MAX_SPEAKERS * 2]
    temperature = args[MAX_SPEAKERS * 2 + 1]
    max_chars = args[MAX_SPEAKERS * 2 + 2]

    # Parse script
    lines = []
    for line in script_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            speaker, _, content = line.partition(":")
            lines.append({"speaker": speaker.strip(), "text": content.strip()})
        elif lines:
            lines[-1]["text"] += " " + line

    if not lines:
        yield None, "⚠️ Không tìm thấy lời thoại hợp lệ (định dạng: Nhân vật: Lời thoại)"
        return

    tts = s.tts_instance
    conv_voices = state.get_conversation_voices()

    mapping = {}
    for name, vid in zip(speaker_names, speaker_voices):
        name = str(name).strip() if name else ""
        if not name:
            continue
        resolved_vid = _resolve_voice_id(str(vid or ""), conv_voices)
        mapping[name.lower()] = resolved_vid

    all_wavs = []
    sr = 24000
    total = len(lines)

    yield None, f"🎭 Đang khởi tạo hội thoại ({total} câu)..."
    start_time = time.time()

    try:
        for i, line in enumerate(lines):
            if _STOP.is_set():
                yield None, "⏹️ Đã dừng hội thoại."
                return

            spk = line["speaker"]
            txt = line["text"]
            yield None, f"⏳ [{i+1}/{total}] {spk}: {txt[:30]}..."

            vid = mapping.get(spk.lower(), "")
            ref_codes = None
            ref_text = ""

            if vid:
                try:
                    vdata = tts.get_preset_voice(vid)
                    ref_codes = vdata.get("codes")
                    ref_text = vdata.get("text", "")
                except Exception:
                    pass

            if ref_codes is None:
                try:
                    default_vid = state.get_default_voice_id()
                    if default_vid:
                        vdata = tts.get_preset_voice(default_vid)
                        ref_codes = vdata.get("codes")
                        ref_text = vdata.get("text", "")
                except Exception:
                    pass

            if hasattr(ref_codes, "cpu"):
                ref_codes = ref_codes.cpu().numpy()

            try:
                wav = tts.infer(
                    txt, ref_codes=ref_codes, ref_text=ref_text,
                    temperature=temperature, max_chars=max_chars,
                    emotion_tag="<|emotion_0|>", skip_normalize=True,
                )
                if wav is not None and len(wav) > 0:
                    all_wavs.append(wav)
                    if i < total - 1 and silence_dur > 0:
                        silence = np.zeros(int(sr * silence_dur), dtype=np.float32)
                        all_wavs.append(silence)
            except Exception as e:
                yield None, f"⚠️ Lỗi câu {i+1}: {e}"
                continue

        if not all_wavs:
            yield None, "❌ Không tạo được âm thanh nào."
            return

        yield None, "🪄 Đang ghép nối âm thanh..."
        final_wav = np.concatenate(all_wavs)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            sf.write(tmp.name, final_wav, sr)
            out_path = tmp.name

        elapsed = time.time() - start_time
        yield out_path, f"✅ Hoàn tất hội thoại! ({total} câu, {elapsed:.1f}s)"

    except Exception as e:
        import traceback
        traceback.print_exc()
        yield None, f"❌ Lỗi hệ thống: {e}"


# ── Speaker Detection ───────────────────────────────────────────

def detect_speakers(script: str):
    if not script:
        return [gr.update() for _ in range(MAX_SPEAKERS * 3)]

    speakers = []
    seen = set()
    for line in script.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            s = line.split(":", 1)[0].strip()
            if s and s not in seen:
                seen.add(s)
                speakers.append(s)

    conv_voices = get_ui_state().get_conversation_voices()
    updates = []
    for i in range(MAX_SPEAKERS):
        if i < len(speakers):
            updates.extend([
                gr.update(value=speakers[i], visible=True),
                gr.update(choices=conv_voices, visible=True),
                gr.update(visible=True),
            ])
        else:
            updates.extend([
                gr.update(value="", visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
            ])
    return updates


# ── Sidebar updater ────────────────────────────────────────────

def update_sidebar():
    """Refresh the sidebar with current model state and GPU status."""
    state = get_ui_state()
    s = state.get_state()
    gpu_html = _gpu_status_html()
    card_html = _model_card_html(s)
    return gpu_html, card_html


# ── UI Layout ───────────────────────────────────────────────────

def build_app() -> gr.Blocks:
    state = get_ui_state()
    initial = state.get_state()

    with gr.Blocks(theme=theme, css=css, title=APP_TITLE, head=head_html) as demo:

        # ── Loading Overlay ────────────────────────────────
        with gr.Group(elem_classes="loading-overlay", visible=False) as loading_overlay:
            gr.HTML(f"""
            <div class="loading-title">🦜 {APP_TITLE}</div>
            <div class="loading-sub">Đang khởi động...</div>
            <div class="spinner"></div>
            <div class="loading-sub" style="margin-top: 20px;" id="loading-status">
                Đang phát hiện phần cứng...
            </div>
            """)

        # ── Two-column layout ──────────────────────────────
        with gr.Row():
            # ── LEFT: Sidebar ─────────────────────────────
            with gr.Column(scale=1, elem_classes="sidebar"):
                # Header
                gr.HTML(f"""
                <div class="header-box">
                    <h1 class="header-title">
                        🦜 <span class="gradient-text">{APP_TITLE}</span>
                    </h1>
                    <p style="color: #94a3b8; margin-top: 6px; font-size: 0.8rem; text-align: center;">
                        Vietnamese Text-to-Speech
                    </p>
                </div>
                """)

                # GPU Status
                gpu_html = _gpu_status_html()
                gr.HTML(
                    f'<div style="background:#1e293b; border-radius:8px; padding:10px 14px; margin-bottom:12px;">'
                    f'<div style="color:#94a3b8; font-size:0.7rem; margin-bottom:4px;">🖥️ THIẾT BỊ</div>'
                    f'<div style="color:white; font-size:0.9rem;">{gpu_html}</div>'
                    f'</div>'
                )

                # User Status
                user_status_html = _user_status_html()
                user_status_box = gr.HTML(value=user_status_html)

                # Auth Tabs
                with gr.Tabs():
                    with gr.TabItem("🔐 Đăng nhập", id="login"):
                        login_email = gr.Textbox(
                            label="📧 Email",
                            placeholder="email@example.com",
                            lines=1,
                        )
                        login_password = gr.Textbox(
                            label="🔒 Mật khẩu",
                            placeholder="Nhập mật khẩu",
                            lines=1,
                            type="password",
                        )
                        login_msg = gr.Textbox(
                            label="📋 Trạng thái",
                            lines=1,
                            interactive=False,
                        )
                        btn_login = gr.Button(
                            "🚀 Đăng nhập",
                            variant="primary",
                        )
                        btn_logout = gr.Button(
                            "🚪 Đăng xuất",
                            variant="secondary",
                            visible=False,
                        )

                    with gr.TabItem("📝 Đăng ký", id="register"):
                        reg_email = gr.Textbox(
                            label="📧 Email",
                            placeholder="email@example.com",
                            lines=1,
                        )
                        reg_username = gr.Textbox(
                            label="👤 Tên người dùng (tùy chọn)",
                            placeholder="Nhập tên",
                            lines=1,
                        )
                        reg_password = gr.Textbox(
                            label="🔒 Mật khẩu",
                            placeholder="Ít nhất 8 ký tự",
                            lines=1,
                            type="password",
                        )
                        reg_confirm = gr.Textbox(
                            label="🔒 Xác nhận mật khẩu",
                            placeholder="Nhập lại mật khẩu",
                            lines=1,
                            type="password",
                        )
                        reg_msg = gr.Textbox(
                            label="📋 Trạng thái",
                            lines=1,
                            interactive=False,
                        )
                        btn_register = gr.Button(
                            "✨ Đăng ký",
                            variant="primary",
                        )

                # Model Info Card - Auto show local model
                card_html = _model_card_html(initial)
                model_info_html = gr.HTML(value=card_html)

                # Local Model Status (Always show, no selection)
                gr.HTML(
                    '<div style="background:#0f172a; border:1px solid #22c55e; border-radius:8px; padding:10px 14px; margin-bottom:12px;">'
                    '<div style="color:#22c55e; font-size:0.8rem;">✅ Model Local</div>'
                    '<div style="color:#e2e8f0; font-size:0.75rem;">./models/phuonganh-tts-v2</div>'
                    '<div style="color:#94a3b8; font-size:0.7rem; margin-top:4px;">Codec: NeuCodec (ONNX)</div>'
                    '</div>'
                )

                # Generation history
                gr.Markdown("### 📜 Lịch sử")
                gr.HTML(
                    '<div id="gen-history" style="max-height:300px; overflow-y:auto;">'
                    '<div style="color:#64748b; font-size:0.8rem; text-align:center; padding:20px;">'
                    'Chưa có lịch sử tạo giọng nói.'
                    '</div></div>'
                )

            # ── RIGHT: Main Content ───────────────────────
            with gr.Column(scale=3):
                # Status bar
                status_md = gr.Markdown(
                    value=initial.status_message(),
                    elem_classes="container",
                )

                # Text input
                text_input = gr.Textbox(
                    label="✏️ Văn bản",
                    lines=6,
                    value=DEFAULT_TEXT,
                    placeholder="Nhập văn bản cần chuyển thành giọng nói...",
                )

                # Voice tabs
                with gr.Tabs():
                    with gr.TabItem("👤 Preset", id="preset") as tab_preset:
                        voice_dd = gr.Dropdown(
                            choices=[],
                            value=None,
                            label="Giọng mẫu",
                            allow_custom_value=True,
                        )

                    with gr.TabItem("🦜 Voice Cloning", id="custom") as tab_custom:
                        ref_audio = gr.Audio(
                            label="Audio giọng mẫu (3-5 giây)",
                            type="filepath",
                        )
                        ref_text = gr.Textbox(
                            label="Nội dung audio mẫu (gõ chính xác, kể cả dấu câu)",
                        )
                        gr.Examples(
                            examples=[
                                [
                                    os.path.join(
                                        os.path.dirname(__file__),
                                        "examples", "audio_ref", "example.wav",
                                    ),
                                    "Ví dụ 2. Tính trung bình của dãy số.",
                                ],
                            ],
                            inputs=[ref_audio, ref_text],
                        )

                # Settings
                with gr.Accordion("⚙️ Cài đặt nâng cao", open=False):
                    with gr.Row():
                        temp_sl = gr.Slider(
                            0.1, 1.5, value=0.7, step=0.1,
                            label="🌡️ Temperature",
                        )
                        max_chars_sl = gr.Slider(
                            128, 512, value=256, step=32,
                            label="📝 Max Chars/đoạn",
                        )
                        batch_size_sl = gr.Slider(
                            1, 16, value=4, step=1,
                            label="📊 Batch Size",
                        )

                use_batch_cb = gr.Checkbox(
                    value=True,
                    label="⚡ Batch Processing (LMDeploy)",
                )

                mode_state = gr.State("preset")
                tab_preset.select(lambda: "preset", outputs=mode_state)
                tab_custom.select(lambda: "custom", outputs=mode_state)

                # Action buttons
                with gr.Row():
                    btn_generate = gr.Button(
                        "🎵 Bắt đầu",
                        variant="primary",
                        scale=2,
                        interactive=False,
                    )
                    btn_stop = gr.Button(
                        "⏹️ Dừng",
                        variant="stop",
                        scale=1,
                        interactive=False,
                    )
                    # Hidden button placeholder for output compatibility
                    btn_load_placeholder = gr.Button(visible=False)

                # Output
                audio_out = gr.Audio(
                    label="🎧 Kết quả",
                    type="filepath",
                    autoplay=True,
                )
                status_out = gr.Textbox(
                    label="📋 Trạng thái",
                    lines=2,
                    max_lines=6,
                    show_copy_button=True,
                )

        # ── Conversation Tab ────────────────────────────────
        with gr.TabItem("🎭 Hội thoại", id="conv") as conv_tab:
            conv_tab.visible = False
            gr.Markdown("### 🎭 Tạo hội thoại đa nhân vật")
            gr.Markdown(
                "*Dùng định dạng `Nhân vật: Lời thoại` trên mỗi dòng.*"
            )
            conv_script = gr.Textbox(
                lines=8,
                placeholder="Phương: Chào mọi người...\nDũng: Ừ, hôm nay...",
                label="Kịch bản",
            )
            with gr.Row():
                btn_detect = gr.Button("🔍 Quét nhân vật", size="sm")
                silence_sl = gr.Slider(
                    0, 3, value=0.1, step=0.1,
                    label="⏱️ Khoảng lặng (s)",
                )

            gr.Markdown("**Cấu hình giọng đọc**")
            speaker_rows = []
            for i in range(MAX_SPEAKERS):
                with gr.Row(visible=False) as row:
                    name_tb = gr.Textbox(label="👤", scale=1, interactive=False)
                    voice_dd_s = gr.Dropdown(label="🎤", scale=3, allow_custom_value=True)
                speaker_rows.append((row, name_tb, voice_dd_s))

            btn_conv = gr.Button(
                "🎭 Bắt đầu hội thoại",
                variant="primary",
                interactive=False,
            )

        # ══════════════════════════════════════════════
        #  Event Bindings
        # ══════════════════════════════════════════════

        # Auto-start on page load with local model
        def on_page_load():
            yield from load_model(
                backbone_choice="phuonganh-tts-v2 (Local)",
                codec_choice="NeuCodec (ONNX)",
                device_choice="Auto",
                force_lmdeploy=False,
                custom_model_id="",
                custom_base_model="",
                hf_token="",
            )

        demo.load(
            fn=on_page_load,
            outputs=[
                status_md, btn_generate, btn_load_placeholder, btn_stop,
                voice_dd, conv_tab,
            ],
        )

        # Generation
        gen_event = btn_generate.click(
            fn=synthesize,
            inputs=[
                text_input, voice_dd, ref_audio, ref_text,
                mode_state,
                gr.State("standard"),
                use_batch_cb, batch_size_sl,
                temp_sl, max_chars_sl,
                gr.State(""),
            ],
            outputs=[audio_out, status_out],
        )

        def on_generate_start():
            return gr.update(interactive=True)

        def on_generate_done():
            return gr.update(interactive=False)

        btn_generate.click(fn=on_generate_start, outputs=btn_stop)
        gen_event.then(fn=on_generate_done, outputs=btn_stop)

        # Stop button
        def on_stop():
            _STOP.set()
            return None, "⏹️ Đã yêu cầu dừng.", gr.update(interactive=False)

        btn_stop.click(
            fn=on_stop,
            outputs=[audio_out, status_out, btn_stop],
        )

        # Speaker detection
        btn_detect.click(
            fn=detect_speakers,
            inputs=conv_script,
            outputs=[
                r for row, _, _ in speaker_rows for r in [row]
            ] + [tb for _, tb, _ in speaker_rows]
            + [dd for _, _, dd in speaker_rows],
        )

        # Conversation generation
        conv_event = btn_conv.click(
            fn=synthesize_conversation,
            inputs=[conv_script]
            + [tb for _, tb, _ in speaker_rows]
            + [dd for _, _, dd in speaker_rows]
            + [silence_sl, temp_sl, max_chars_sl, gr.State("")],
            outputs=[audio_out, status_out],
        )

        btn_conv.click(fn=on_generate_start, outputs=btn_stop)
        conv_event.then(fn=on_generate_done, outputs=btn_stop)

        # ── Auth Event Bindings ─────────────────────────────

        # Login
        btn_login.click(
            fn=handle_login,
            inputs=[login_email, login_password],
            outputs=[login_msg, btn_login, btn_logout, user_status_box],
        )

        # Register
        btn_register.click(
            fn=handle_register,
            inputs=[reg_email, reg_password, reg_confirm, reg_username],
            outputs=[reg_msg, reg_email, reg_password, reg_confirm],
        )

        # Logout
        btn_logout.click(
            fn=handle_logout,
            outputs=[login_msg, btn_login, btn_logout, user_status_box],
        )

    return demo


# ── Entry Point ────────────────────────────────────────────────

def main():
    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    is_colab = os.getenv("COLAB_RELEASE_TAG") is not None
    share = is_colab or os.getenv("GRADIO_SHARE") == "true"

    if server_name == "0.0.0.0" and os.getenv("GRADIO_SHARE") is None:
        share = False

    print(f"🚀 Khởi động {APP_TITLE}...")
    demo = build_app()
    demo.queue().launch(
        server_name=server_name,
        server_port=server_port,
        share=share,
    )


if __name__ == "__main__":
    main()
