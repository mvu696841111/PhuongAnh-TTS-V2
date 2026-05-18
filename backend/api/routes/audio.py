"""
Audio routes for PhuongAnh-TTS Backend.
Handles TTS generation, audio management, and voice listing.

Enhanced with:
- Chunked TTS generation for long texts
- Progress tracking via job polling
- Job queue for concurrency management
- Cancellation support
"""

import asyncio
import hashlib
import logging
import os
import tempfile
import time
from typing import Optional, AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
import numpy as np

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
from phuonganh_tts.chunked_generator import ChunkedTTSGenerator, ChunkedTTSConfig, ChunkConfig, MergeConfig

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
    """Get list of available voices."""
    voices = [
        {"id": "Tuyen", "name": "Tuyên", "description": "Nam miền Bắc - Giọng nam trung, ấm áp", "gender": "male", "language": "vi-VN"},
        {"id": "Vinh", "name": "Xuân Vĩnh", "description": "Nam miền Nam - Giọng nam trẻ, năng động", "gender": "male", "language": "vi-VN"},
        {"id": "Doan", "name": "Thục Đoan", "description": "Nữ miền Nam - Giọng nữ trung, dịu dàng", "gender": "female", "language": "vi-VN"},
        {"id": "Ly", "name": "Trúc Ly", "description": "Nữ miền Bắc - Giọng nữ cao, trong sáng", "gender": "female", "language": "vi-VN"},
    ]
    
    return VoiceListResponse(
        voices=[VoiceInfo(**v) for v in voices],
        total=len(voices),
        categories=["Nam miền Bắc", "Nam miền Nam", "Nữ miền Nam", "Nữ miền Bắc"]
    )


# ===========================================
# Global TTS Engine (Singleton)
# ===========================================

_tts_engine = None
_chunked_generator = None
_active_jobs = {}  # job_id -> status


@dataclass
class ChunkedGenerationConfig:
    """Configuration for chunked TTS generation."""
    # Chunking settings
    target_chars_per_chunk: int = 256
    max_chars_per_chunk: int = 350
    max_sentences_per_chunk: int = 10
    
    # Generation settings
    max_retries: int = 2
    chunk_timeout: float = 60.0
    
    # Memory management
    clear_memory_after_chunk: bool = True
    gc_interval: int = 5
    
    # Merging settings
    silence_duration: float = 0.15
    normalize_volume: bool = True


def get_tts_engine():
    """Get or create TTS engine instance."""
    global _tts_engine
    if _tts_engine is None:
        try:
            from phuonganh_tts import PhuongAnh
            
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


def get_chunked_generator():
    """Get or create chunked TTS generator instance."""
    global _chunked_generator
    if _chunked_generator is None:
        try:
            engine = get_tts_engine()
            _chunked_generator = ChunkedTTSGenerator(engine, get_tts_config())
            logger.info("Chunked TTS generator initialized")
        except Exception as e:
            logger.error(f"Failed to initialize chunked generator: {e}")
            raise
    return _chunked_generator


def get_tts_config() -> ChunkedTTSConfig:
    """Get TTS configuration for chunked generation."""
    from phuonganh_utils.smart_chunking import ChunkConfig
    from phuonganh_utils.audio_merge import MergeConfig
    
    chunk_config = ChunkConfig(
        target_chars_per_chunk=500,
        max_chars_per_chunk=1000,
        max_sentences_per_chunk=10,  # TỐI ĐA 10 CÂU MỖI ĐOẠN
        min_chars_per_chunk=20,
    )
    
    merge_config = MergeConfig(
        silence_duration=0.15,
        sentence_end_silence=0.3,
        clause_silence=0.15,
        normalize_volume=True,
    )
    
    return ChunkedTTSConfig(
        chunk_config=chunk_config,
        merge_config=merge_config,
        max_retries=2,
        chunk_timeout=60.0,
        clear_memory_after_chunk=True,
        gc_interval=5,
        enable_caching=True,
    )


# ===========================================
# Standard TTS Generation (FormData)
# ===========================================

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
    Uses chunked generation for long texts.
    """
    start_time = time.time()
    
    # Validate text
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng nhập văn bản"
        )
    
    text = text.strip()
    if len(text) > 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Văn bản quá dài. Tối đa 10000 ký tự."
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
    logger.info(f"TTS FormData: user={user_id}, text_len={len(text)}, voice={voice_id}")
    
    try:
        engine = get_tts_engine()
        
        voice_name = voice_id if voice_id in valid_voices else "Ly"
        try:
            voice = engine.get_preset_voice(voice_name)
        except Exception:
            voice = engine.get_preset_voice()
        
        # Generate audio using chunked generator for longer texts
        generator = get_chunked_generator()
        
        def progress_callback(current: int, total: int, message: str, partial: Optional[np.ndarray] = None):
            logger.debug(f"Chunk {current}/{total}: {message}")
        
        result = generator.generate(
            text=text,
            voice=voice,
            progress_callback=progress_callback,
        )
        
        if result.status.value == "failed":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Tạo audio thất bại: {result.error}"
            )
        
        # Save audio to temp file
        import soundfile as sf
        output_file = tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False)
        sf.write(output_file.name, result.audio, engine.sample_rate)
        output_file.close()
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"TTS generated in {processing_time:.0f}ms ({result.successful_chunks}/{result.total_chunks} chunks): {output_file.name}")
        
        return FileResponse(
            path=output_file.name,
            filename=f"phuonganh-tts-{voice_id.lower()}.{format}",
            media_type=f"audio/{format}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tạo audio: {str(e)}"
        )


# ===========================================
# Streaming TTS Generation (SSE Progress)
# ===========================================

@router.post(
    "/generate-stream",
    summary="Generate TTS audio with streaming progress",
    description="Generate TTS with Server-Sent Events for real-time progress updates.",
)
async def generate_tts_stream(
    text: str = Form(...),
    voice_id: str = Form(default="Ly"),
    format: str = Form(default="wav"),
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Generate TTS audio with streaming progress updates.
    
    Uses Server-Sent Events (SSE) to send:
    - Progress updates
    - Partial audio chunks (for preview)
    - Final audio file
    """
    
    async def event_generator() -> AsyncGenerator[dict, None]:
        nonlocal text, voice_id, format
        
        start_time = time.time()
        
        # Validate inputs
        if not text or not text.strip():
            yield {"event": "error", "data": "Vui lòng nhập văn bản"}
            return
        
        text = text.strip()
        if len(text) > 10000:
            yield {"event": "error", "data": "Văn bản quá dài. Tối đa 10000 ký tự."}
            return
        
        valid_voices = ["Ly", "Tuyen", "Vinh", "Doan"]
        if voice_id not in valid_voices:
            voice_id = "Ly"
        
        valid_formats = ["wav", "mp3"]
        if format not in valid_formats:
            format = "wav"
        
        user_id = str(current_user["_id"]) if current_user else "anonymous"
        job_id = hashlib.md5(f"{user_id}_{time.time()}".encode()).hexdigest()[:8]
        
        try:
            # Initialize
            yield {
                "event": "start",
                "data": f"{{\"job_id\": \"{job_id}\", \"text_length\": {len(text)}, \"voice\": \"{voice_id}\"}}"
            }
            
            engine = get_tts_engine()
            generator = get_chunked_generator()
            
            voice_name = voice_id if voice_id in valid_voices else "Ly"
            try:
                voice = engine.get_preset_voice(voice_name)
            except Exception:
                voice = engine.get_preset_voice()
            
            audio_chunks = []
            
            def progress_callback(current: int, total: int, message: str, partial: Optional[np.ndarray] = None):
                # This runs in the thread pool, but we need to communicate back
                pass
            
            # Generate with async wrapper
            loop = asyncio.get_event_loop()
            
            # Progress tracking via polling (since callback runs in thread)
            def sync_generate():
                return generator.generate(
                    text=text,
                    voice=voice,
                    progress_callback=None,  # We'll track progress separately
                )
            
            result = await loop.run_in_executor(None, sync_generate)
            
            if result.status.value == "failed":
                yield {"event": "error", "data": f"Tạo audio thất bại: {result.error}"}
                return
            
            # Send progress events
            for i, chunk_result in enumerate(result.chunk_results):
                yield {
                    "event": "chunk_complete",
                    "data": f"{{\"chunk\": {i + 1}, \"total\": {result.total_chunks}, \"success\": {chunk_result.success}}}"
                }
                
                if chunk_result.audio is not None:
                    audio_chunks.append(chunk_result.audio)
            
            # Merge audio
            yield {"event": "merging", "data": "Đang ghép audio..."}
            
            from phuonganh_utils.audio_merge import merge_audio_chunks
            final_audio = merge_audio_chunks(
                audio_chunks,
                sample_rate=engine.sample_rate,
                silence_duration=0.15,
                normalize=True
            )
            
            # Save to temp file
            import soundfile as sf
            output_file = tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False)
            sf.write(output_file.name, final_audio, engine.sample_rate)
            output_file.close()
            
            processing_time = (time.time() - start_time) * 1000
            
            yield {
                "event": "complete",
                "data": f"{{\"job_id\": \"{job_id}\", \"file\": \"{output_file.name}\", \"duration_ms\": {processing_time:.0f}, \"chunks\": {result.successful_chunks}}}"
            }
            
        except Exception as e:
            logger.error(f"Streaming TTS error: {e}")
            yield {"event": "error", "data": str(e)}
    
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


# ===========================================
# Job-based TTS Generation
# ===========================================

@router.post(
    "/generate-async",
    summary="Submit async TTS job",
    description="Submit a TTS job and get a job ID for tracking.",
)
async def submit_tts_job(
    text: str = Form(...),
    voice_id: str = Form(default="Ly"),
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Submit a TTS job for async processing.
    
    Returns a job_id that can be used to track progress and get results.
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng nhập văn bản"
        )
    
    text = text.strip()
    if len(text) > 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Văn bản quá dài. Tối đa 10000 ký tự."
        )
    
    valid_voices = ["Ly", "Tuyen", "Vinh", "Doan"]
    if voice_id not in valid_voices:
        voice_id = "Ly"
    
    user_id = str(current_user["_id"]) if current_user else "anonymous"
    logger.info(f"TTS Job: user={user_id}, voice={voice_id}, chars={len(text)}")
    job_id = hashlib.md5(f"{user_id}_{time.time()}".encode()).hexdigest()[:12]
    
    # Store job info
    _active_jobs[job_id] = {
        "job_id": job_id,
        "text": text,
        "voice_id": voice_id,
        "status": "pending",
        "progress": 0,
        "created_at": time.time(),
        "result": None,
        "error": None,
    }
    
    # Start background generation
    asyncio.create_task(process_tts_job(job_id, text, voice_id))
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job submitted successfully"
    }


async def process_tts_job(job_id: str, text: str, voice_id: str):
    """Background task to process TTS job."""
    logger.info(f"[process_tts_job] job_id={job_id}, voice_id={voice_id}, text_len={len(text)}")
    
    if job_id not in _active_jobs:
        return
    
    try:
        _active_jobs[job_id]["status"] = "running"
        
        engine = get_tts_engine()
        
        # XÓA CACHE khi đổi giọng để tránh dùng audio cũ
        import gc
        gc.collect()
        
        # Tạo generator mới cho giọng này (không dùng cache cũ)
        generator = ChunkedTTSGenerator(tts_backend=engine, config=get_tts_config())
        
        logger.info(f"TTS Job: voice_id={voice_id}")
        
        try:
            voice = engine.get_preset_voice(voice_id)
            logger.info(f"Got voice: {voice.get('id', voice.get('name', 'unknown'))}")
        except Exception as e:
            logger.warning(f"Failed to get voice '{voice_id}': {e}, using default")
            voice = engine.get_preset_voice()
        
        # Run blocking TTS generation in thread pool — auto-repeat 2x for speed
        for run_idx in range(2):
            if run_idx > 0:
                logger.info(f"Auto-repeat run {run_idx + 1}/2 for job {job_id}")
                gc.collect()
                generator = ChunkedTTSGenerator(tts_backend=engine, config=get_tts_config())

            result = await asyncio.to_thread(
                generator.generate,
                text=text,
                voice=voice,
                progress_callback=None,
            )

            if result.status.value != "completed":
                break

        if result.status.value == "completed":
            # Save audio
            import soundfile as sf
            output_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(output_file.name, result.audio, engine.sample_rate)
            output_file.close()
            
            _active_jobs[job_id]["status"] = "completed"
            _active_jobs[job_id]["result"] = {
                "file": output_file.name,
                "chunks": result.successful_chunks,
                "total_chunks": result.total_chunks,
                "duration_ms": result.total_duration_ms,
            }
        else:
            _active_jobs[job_id]["status"] = "failed"
            _active_jobs[job_id]["error"] = result.error
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        _active_jobs[job_id]["status"] = "failed"
        _active_jobs[job_id]["error"] = str(e)


@router.get(
    "/job/{job_id}",
    summary="Get TTS job status",
    description="Get the status and result of a TTS job.",
)
async def get_job_status(job_id: str):
    """Get the status of a TTS job."""
    if job_id not in _active_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    job = _active_jobs[job_id]
    
    response = {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
    }
    
    if job["status"] == "completed" and job["result"]:
        response["result"] = job["result"]
    elif job["status"] == "failed":
        response["error"] = job["error"]
    
    return response


@router.get(
    "/job/{job_id}/audio",
    summary="Download job audio",
    description="Download the audio file for a completed job.",
)
async def download_job_audio(job_id: str):
    """Download the audio for a completed job."""
    if job_id not in _active_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    job = _active_jobs[job_id]
    
    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is {job['status']}, not completed"
        )
    
    if not job["result"] or "file" not in job["result"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No audio file available"
        )
    
    audio_file = job["result"]["file"]
    
    if not os.path.exists(audio_file):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    return FileResponse(
        path=audio_file,
        filename=f"phuonganh-tts-{job_id}.wav",
        media_type="audio/wav"
    )


@router.post(
    "/job/{job_id}/cancel",
    summary="Cancel TTS job",
    description="Cancel a pending or running TTS job.",
)
async def cancel_job(job_id: str):
    """Cancel a TTS job."""
    if job_id not in _active_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    job = _active_jobs[job_id]
    
    if job["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is already {job['status']}"
        )
    
    job["status"] = "cancelled"
    
    # Try to cancel the generator if running
    try:
        generator = get_chunked_generator()
        generator.cancel()
    except Exception:
        pass
    
    return {"message": "Job cancelled", "job_id": job_id}


# ===========================================
# Legacy JSON Endpoint (Maintained for compatibility)
# ===========================================

@router.post(
    "/generate",
    response_model=AudioGenerationResponse,
    summary="Generate TTS audio",
    description="Convert text to speech with specified voice.",
)
async def generate_tts(
    request: AudioGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """Generate TTS audio from text (JSON endpoint)."""
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
    
    # Check text length
    from core.config import get_subscription_limits
    limits = get_subscription_limits()
    max_text = limits.get_max_text_length(plan)
    
    if len(request.text) > max_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Text too long. Maximum {max_text} characters for {plan} plan."
        )
    
    logger.info(f"TTS generation requested: user={user_id}, text_len={len(request.text)}, voice={request.voice_id}")
    
    processing_time = (time.time() - start_time) * 1000
    
    return AudioGenerationResponse(
        audio_id="demo-audio-id",
        filename=f"tts_{int(time.time())}.{request.format.value}",
        duration=len(request.text) / 15.0,
        filesize=len(request.text) * 1000,
        format=request.format,
        text_length=len(request.text),
        characters_used=len(request.text),
        processing_time_ms=processing_time,
        is_watermarked=limits.has_watermark(plan)
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
    """List user's audio files with pagination."""
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
    """Get audio file information."""
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
    """Delete an audio file."""
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
    """Get a temporary download URL for the audio file."""
    user_id = str(current_user["_id"])
    
    audio = await audio_service.get_audio(audio_id, user_id)
    
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    await audio_service.increment_download_count(audio_id)
    
    return DownloadResponse(
        audio_id=audio_id,
        filename=audio.get("filename", f"audio.{audio.get('format', 'wav')}"),
        filesize=audio.get("filesize", 0),
        format=audio.get("format", "wav"),
        download_url=f"/api/audio/{audio_id}/file",
        expires_in=3600
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
    ref_audio,
    ref_text: str = "",
    voice_name: str = "",
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """Clone a voice from reference audio."""
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
    """Stream TTS audio in real-time."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Streaming TTS coming soon"
    )
