"""
Audio routes for PhuongAnh-TTS Backend.
Handles TTS generation, audio management, and voice listing.
"""

import logging
import os
import tempfile
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from models.schemas.audio import (
    AudioResponse,
    AudioListResponse,
    AudioGenerationRequest,
    AudioGenerationResponse,
    VoiceInfo,
    VoiceListResponse,
    DownloadResponse,
)
from api.dependencies import (
    get_db,
    get_current_user,
    get_current_user_optional,
    get_audio_service,
    get_subscription_service,
    get_auth_service,
    RequirePlan,
    RequirePermission,
)
from services.audio_service import AudioService
from services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["Audio"])


# ===========================================
# Voice Management (Public)
# ===========================================

@router.get(
    "/voices",
    response_model=VoiceListResponse,
    summary="List available voices",
    description="Get list of all available TTS voices."
)
async def list_voices(
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    Get list of available voices.
    
    This endpoint is public - no authentication required.
    However, voice cloning features require Plus/Pro subscription.
    """
    # Predefined voices from the model
    voices = [
        {
            "id": "Tuyen",
            "name": "Tuyên",
            "description": "Nam miền Bắc - Giọng nam trung, ấm áp",
            "gender": "male",
            "language": "vi-VN",
            "preview_url": None
        },
        {
            "id": "Vinh",
            "name": "Xuân Vĩnh",
            "description": "Nam miền Nam - Giọng nam trẻ, năng động",
            "gender": "male",
            "language": "vi-VN",
            "preview_url": None
        },
        {
            "id": "Doan",
            "name": "Thục Đoan",
            "description": "Nữ miền Nam - Giọng nữ trung, dịu dàng",
            "gender": "female",
            "language": "vi-VN",
            "preview_url": None
        },
        {
            "id": "Ly",
            "name": "Trúc Ly",
            "description": "Nữ miền Bắc - Giọng nữ cao, trong sáng",
            "gender": "female",
            "language": "vi-VN",
            "preview_url": None
        },
    ]
    
    return VoiceListResponse(
        voices=[
            VoiceInfo(**v) for v in voices
        ],
        total=len(voices),
        categories=["Nam miền Bắc", "Nam miền Nam", "Nữ miền Nam", "Nữ miền Bắc"]
    )


# ===========================================
# TTS Generation (Authenticated)
# ===========================================

@router.post(
    "/generate",
    response_model=AudioGenerationResponse,
    summary="Generate TTS audio",
    description="Convert text to speech with specified voice."
)
async def generate_tts(
    request: AudioGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Generate TTS audio from text.
    
    Requires authentication.
    
    - **text**: Text to convert to speech (1-10000 characters)
    - **voice_id**: Voice ID to use
    - **format**: Audio format (wav, mp3, flac, ogg)
    - **speed**: Speech speed (0.5-2.0)
    - **temperature**: Generation temperature (0.1-2.0)
    
    Free users:
    - Audio will have watermark
    - Limited to 500 characters
    - Max 30 seconds duration
    """
    import time
    start_time = time.time()
    
    user_id = str(current_user["_id"])
    plan = current_user.get("subscription_plan", "free")
    
    # Check usage limits
    can_generate, error = await audio_service.check_usage_limits(user_id, len(request.text))
    if not can_generate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error
        )
    
    # Check text length limit
    from core.config import get_subscription_limits
    limits = get_subscription_limits()
    max_text = limits.get_max_text_length(plan)
    
    if len(request.text) > max_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Text too long. Maximum {max_text} characters for {plan} plan."
        )
    
    # In a real implementation, this would call the TTS engine
    # For now, we'll create a placeholder response
    # The actual TTS generation would integrate with PhuongAnhTTS
    
    processing_time = (time.time() - start_time) * 1000
    
    # Placeholder - in production, this would call the actual TTS engine
    logger.info(f"TTS generation requested: user={user_id}, text_len={len(request.text)}, voice={request.voice_id}")
    
    # For demo purposes, return a mock response
    return AudioGenerationResponse(
        audio_id="demo-audio-id",
        filename=f"tts_{int(time.time())}.{request.format.value}",
        duration=len(request.text) / 15.0,  # Estimate: 15 chars per second
        filesize=len(request.text) * 1000,  # Placeholder
        format=request.format,
        text_length=len(request.text),
        characters_used=len(request.text),
        processing_time_ms=processing_time,
        is_watermarked=limits.has_watermark(plan)
    )


# ===========================================
# TTS Generation - Web FormData (Public with optional auth)
# ===========================================

# Global engine instance (loaded once)
_tts_engine = None

def get_tts_engine():
    """Get or create TTS engine instance."""
    global _tts_engine
    if _tts_engine is None:
        try:
            from pathlib import Path
            from phuonganh_tts import PhuongAnh
            
            # Resolve to absolute paths - go up 2 levels from backend/api/routes/
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            backbone_repo = str((base_dir / "models" / "phuonganh-tts-v2").resolve())
            codec_repo = str((base_dir / "models" / "neucodec-onnx-decoder-int8").resolve())
            
            _tts_engine = PhuongAnh(
                mode="standard",
                backbone_repo=backbone_repo,
                backbone_device="cuda",
                codec_repo=codec_repo,
                codec_device="cuda",
            )
            logger.info("TTS engine loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load TTS engine: {e}")
            raise
    return _tts_engine


@router.post(
    "/generate-form",
    summary="Generate TTS audio from form data",
    description="Convert text to speech using FormData (for web frontend).",
)
async def generate_tts_form(
    text: str = Form(...),
    voice_id: str = Form(default="Ly"),
    format: str = Form(default="wav"),
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Generate TTS audio from FormData (for web frontend).
    
    This endpoint accepts FormData instead of JSON for easier web integration.
    
    - **text**: Text to convert to speech (1-5000 characters)
    - **voice_id**: Voice ID (default: Ly)
    - **format**: Audio format (wav, mp3)
    """
    start_time = time.time()
    
    # Validate text
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng nhập văn bản"
        )
    
    text = text.strip()
    if len(text) > 5000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Văn bản quá dài. Tối đa 5000 ký tự."
        )
    
    # Validate voice_id
    valid_voices = ["Ly", "Tuyen", "Vinh", "Doan"]
    if voice_id not in valid_voices:
        voice_id = "Ly"
    
    # Validate format
    valid_formats = ["wav", "mp3"]
    if format not in valid_formats:
        format = "wav"
    
    user_id = str(current_user["_id"]) if current_user else "anonymous"
    plan = current_user.get("subscription_plan", "free") if current_user else "free"
    
    logger.info(f"TTS FormData: user={user_id}, text_len={len(text)}, voice={voice_id}")
    
    # Try to use local TTS engine
    try:
        engine = get_tts_engine()
        
        # Get voice preset
        voice_name = voice_id if voice_id in ["Ly", "Tuyen", "Vinh", "Doan"] else "Ly"
        try:
            voice = engine.get_preset_voice(voice_name)
        except Exception:
            # Fallback to default voice
            voice = engine.get_preset_voice()
        
        # Generate audio using infer method
        wav = engine.infer(
            text=text,
            voice=voice,
        )
        
        # Save audio to temp file
        import soundfile as sf
        output_file = tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False)
        sf.write(output_file.name, wav, engine.sample_rate)
        output_file.close()
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"TTS generated in {processing_time:.0f}ms: {output_file.name}")
        
        # Return audio file
        return FileResponse(
            path=output_file.name,
            filename=f"phuonganh-tts-{voice_id.lower()}.{format}",
            media_type=f"audio/{format}"
        )
        
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tạo audio: {str(e)}"
        )


# ===========================================
# Audio Management (Authenticated)
# ===========================================

@router.get(
    "/list",
    response_model=AudioListResponse,
    summary="List user's audio files",
    description="Get paginated list of user's generated audio files."
)
async def list_audios(
    page: int = 1,
    per_page: int = 20,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
):
    """
    List user's audio files with pagination.
    
    - **page**: Page number (default 1)
    - **per_page**: Items per page (default 20, max 100)
    """
    user_id = str(current_user["_id"])
    
    audios, total = await audio_service.list_user_audios(
        user_id=user_id,
        page=page,
        per_page=min(per_page, 100)
    )
    
    pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    
    return AudioListResponse(
        items=[AudioResponse(**a) for a in audios],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages
    )


@router.get(
    "/{audio_id}",
    response_model=AudioResponse,
    summary="Get audio file info",
    description="Get details of a specific audio file."
)
async def get_audio(
    audio_id: str,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
):
    """
    Get audio file information.
    """
    user_id = str(current_user["_id"])
    
    audio = await audio_service.get_audio(audio_id, user_id)
    
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    return AudioResponse(**audio)


@router.delete(
    "/{audio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete audio file",
    description="Delete a specific audio file."
)
async def delete_audio(
    audio_id: str,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
):
    """
    Delete an audio file.
    """
    user_id = str(current_user["_id"])
    
    success = await audio_service.delete_audio(audio_id, user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    logger.info(f"Audio deleted: {audio_id} by user {user_id}")
    
    return None


@router.get(
    "/{audio_id}/download",
    response_model=DownloadResponse,
    summary="Get audio download URL",
    description="Get a temporary download URL for an audio file."
)
async def get_download_url(
    audio_id: str,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
):
    """
    Get a temporary download URL for the audio file.
    """
    user_id = str(current_user["_id"])
    
    audio = await audio_service.get_audio(audio_id, user_id)
    
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # Increment download count
    await audio_service.increment_download_count(audio_id)
    
    return DownloadResponse(
        audio_id=audio_id,
        filename=audio.get("filename", f"audio.{audio.get('format', 'wav')}"),
        filesize=audio.get("filesize", 0),
        format=audio.get("format", "wav"),
        download_url=f"/api/audio/{audio_id}/file",
        expires_in=3600
    )


@router.get(
    "/{audio_id}/file",
    summary="Download audio file",
    description="Download the actual audio file."
)
async def download_audio_file(
    audio_id: str,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
):
    """
    Download the actual audio file.
    """
    from pathlib import Path
    
    user_id = str(current_user["_id"])
    
    audio = await audio_service.get_audio(audio_id, user_id)
    
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    filepath = Path(audio.get("filepath", ""))
    
    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found on disk"
        )
    
    return FileResponse(
        path=str(filepath),
        filename=audio.get("filename", "audio.wav"),
        media_type="audio/wav"
    )


# ===========================================
# Voice Cloning (Plus/Pro Only)
# ===========================================

@router.post(
    "/clone",
    summary="Clone voice from audio",
    description="Clone a voice using a reference audio file.",
    dependencies=[Depends(RequirePlan("plus"))],
)
async def clone_voice(
    ref_audio: UploadFile = File(...),
    ref_text: str = "",
    voice_name: str = "",
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Clone a voice from reference audio.
    
    Requires Plus or Pro subscription.
    
    - **ref_audio**: Reference audio file (3-30 seconds recommended)
    - **ref_text**: Transcript of the reference audio
    - **voice_name**: Name for the cloned voice
    """
    # Validate file type
    allowed_types = ["audio/wav", "audio/mp3", "audio/mpeg", "audio/ogg", "audio/flac"]
    if ref_audio.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )
    
    user_id = str(current_user["_id"])
    logger.info(f"Voice cloning requested by user {user_id}")
    
    # In production, this would:
    # 1. Save the uploaded file
    # 2. Process with the codec encoder
    # 3. Store the voice embedding
    # 4. Return a voice ID
    
    return {
        "message": "Voice cloning feature coming soon",
        "status": "pending",
        "voice_id": None
    }


# ===========================================
# Streaming TTS (Plus/Pro Only)
# ===========================================

@router.post(
    "/stream",
    summary="Stream TTS audio",
    description="Stream TTS audio in real-time.",
    dependencies=[Depends(RequirePlan("plus"))],
)
async def stream_tts(
    request: AudioGenerationRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Stream TTS audio in real-time.
    
    Requires Plus or Pro subscription.
    """
    # In production, this would use WebSocket or chunked transfer encoding
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Streaming TTS coming soon"
    )
