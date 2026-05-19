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
from datetime import datetime
from typing import Optional, AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
import aiofiles

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
    audio_service: AudioService = Depends(get_audio_service),
):
    """
    Generate TTS audio from FormData (for web frontend).
    Uses chunked generation for long texts.
    Enforces usage limits based on subscription plan.
    """
    start_time = time.time()
    
    # Validate text
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng nhập văn bản"
        )
    
    text = text.strip()
    text_length = len(text)
    
    # Get user limits info
    if current_user:
        user_id = str(current_user["_id"])
        limits_info = await audio_service.get_user_limits_info(user_id)
        
        # Check text length limit
        max_text_length = limits_info["limits"]["max_text_length"]
        if text_length > max_text_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Văn bản quá dài. Tối đa {max_text_length} ký tự cho gói {limits_info['plan']}. Bạn đang có {text_length} ký tự."
            )
        
        # Check daily audio limit
        daily_limit = limits_info["limits"]["daily_audio_limit"]
        daily_used = limits_info["usage"]["daily_audio_count"]
        if daily_limit > 0 and daily_used >= daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Bạn đã sử dụng hết {daily_limit} lượt TTS hôm nay. Nâng cấp gói để sử dụng thêm."
            )
        
        # Check monthly chars limit
        monthly_limit = limits_info["limits"]["monthly_chars_limit"]
        monthly_used = limits_info["usage"]["monthly_chars_used"]
        if monthly_limit > 0 and monthly_used + text_length > monthly_limit:
            remaining = max(0, monthly_limit - monthly_used)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Bạn đã sử dụng hết giới hạn ký tự tháng này. Còn lại {remaining} ký tự."
            )
    else:
        # Anonymous users - use free limits
        if text_length > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Văn bản quá dài. Tối đa 500 ký tự cho người dùng chưa đăng nhập."
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
    logger.info(f"TTS FormData: user={user_id}, text_len={text_length}, voice={voice_id}")
    
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
        
        # Check duration limit AFTER generation (estimated)
        estimated_duration = len(text) / 15  # ~15 chars per second
        if current_user:
            max_duration = limits_info["limits"]["max_duration"]
            if estimated_duration > max_duration:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Audio quá dài ({estimated_duration:.0f}s). Tối đa {max_duration}s cho gói {limits_info['plan']}."
                )
        
        # Save audio to temp file
        import soundfile as sf
        output_file = tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False)
        sf.write(output_file.name, result.audio, engine.sample_rate)
        output_file.close()
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"TTS generated in {processing_time:.0f}ms ({result.successful_chunks}/{result.total_chunks} chunks): {output_file.name}")
        
        # Log usage for authenticated users
        if current_user:
            from api.dependencies import get_db
            db = get_db()
            await db.usage_logs.insert_one({
                "user_id": ObjectId(str(current_user["_id"])),
                "action": "tts_generate",
                "timestamp": datetime.utcnow(),
                "characters_used": text_length,
                "metadata": {
                    "voice": voice_id,
                    "duration": estimated_duration,
                    "plan": limits_info["plan"]
                }
            })
        
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
    session_id: str = Form(default=None),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    audio_service: AudioService = Depends(get_audio_service),
    request: Request = None,
):
    """
    Submit a TTS job for async processing.
    Enforces usage limits based on subscription plan.
    
    Returns a job_id that can be used to track progress and get results.
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng nhập văn bản"
        )
    
    text = text.strip()
    text_length = len(text)
    
    # Get user info
    user_id = str(current_user["_id"]) if current_user else None
    # Use session_id from form, or generate one if not provided
    if not current_user:
        if not session_id:
            client_host = request.client.host if request else "unknown"
            session_id = hashlib.md5(f"{client_host}_{time.time()}".encode()).hexdigest()[:16]
    
    # Check limits using SubscriptionService
    from services.subscription_service import SubscriptionService
    sub_service = SubscriptionService(audio_service.db)
    allowed, error_msg, quota_info = await sub_service.check_limits(
        text=text,
        user_id=user_id,
        session_id=session_id,
    )
    
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_msg
        )
    
    limits_info = quota_info
    
    valid_voices = ["Ly", "Tuyen", "Vinh", "Doan"]
    if voice_id not in valid_voices:
        voice_id = "Ly"
    
    user_id_for_job = str(current_user["_id"]) if current_user else "anonymous"
    if not current_user:
        logger.info(f"TTS Job: user=anonymous, session={session_id[:8]}..., voice={voice_id}, chars={text_length}")
    else:
        session_id = None
        logger.info(f"TTS Job: user={user_id_for_job}, voice={voice_id}, chars={text_length}")
    job_id = hashlib.md5(f"{user_id}_{time.time()}".encode()).hexdigest()[:12]
    
    # Store job info with limits info for duration check later
    _active_jobs[job_id] = {
        "job_id": job_id,
        "text": text,
        "voice_id": voice_id,
        "status": "pending",
        "progress": 0,
        "created_at": time.time(),
        "result": None,
        "error": None,
        "user_id": user_id_for_job,
        "session_id": session_id,
        "text_length": text_length,
        "plan": limits_info.get("plan", {}).get("name", "Miễn phí") if current_user else "anonymous",
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
            
            # Check duration limit after generation
            job_info = _active_jobs.get(job_id, {})
            plan = job_info.get("plan", "anonymous")
            if plan != "anonymous":
                estimated_duration = len(job_info.get("text", "")) / 15  # ~15 chars per second
                from core.config import get_subscription_limits
                limits = get_subscription_limits()
                max_duration = limits.get_max_duration(plan)
                if estimated_duration > max_duration:
                    _active_jobs[job_id]["status"] = "failed"
                    _active_jobs[job_id]["error"] = f"Audio quá dài ({estimated_duration:.0f}s). Tối đa {max_duration}s cho gói {plan}."
                    os.unlink(output_file.name)
                    return
            
            _active_jobs[job_id]["status"] = "completed"
            _active_jobs[job_id]["result"] = {
                "file": output_file.name,
                "chunks": result.successful_chunks,
                "total_chunks": result.total_chunks,
                "duration_ms": result.total_duration_ms,
            }
            
            # Save audio to database for history (all users including anonymous)
            job_info = _active_jobs[job_id]
            current_user = job_info.get("user_id")
            session_id = job_info.get("session_id")
            
            if current_user or session_id:
                from bson import ObjectId
                from core.database import get_database
                try:
                    db = get_database()
                    
                    # Read audio file
                    async with aiofiles.open(output_file.name, "rb") as f:
                        audio_data = await f.read()
                    
                    filesize = len(audio_data)
                    duration = result.total_duration_ms / 1000 if result.total_duration_ms else 0
                    
                    # Determine user identifier
                    if current_user and current_user != "anonymous":
                        user_id_obj = ObjectId(current_user)
                        is_anonymous = False
                    else:
                        # Use session_id for anonymous users
                        user_id_obj = session_id
                        is_anonymous = True
                    
                    # Save to audio_files collection
                    audio_doc = {
                        "user_id": user_id_obj,
                        "is_anonymous": is_anonymous,
                        "filename": f"tts_{job_id}.wav",
                        "filepath": output_file.name,
                        "filesize": filesize,
                        "duration": duration,
                        "text_input": text[:500],  # Store first 500 chars
                        "voice_id": voice_id,
                        "format": "wav",
                        "is_watermarked": False,
                        "download_count": 0,
                        "created_at": datetime.utcnow(),
                        "metadata": {
                            "job_id": job_id,
                            "plan": plan,
                            "characters_used": job_info.get("text_length", 0)
                        }
                    }
                    
                    insert_result = await db.audio_files.insert_one(audio_doc)
                    audio_id = str(insert_result.inserted_id)
                    logger.info(f"✓ Saved audio to DB: {audio_id} for job {job_id} (anonymous={is_anonymous})")
                    
                    # Also log to usage_logs (only for logged-in users)
                    if not is_anonymous:
                        await db.usage_logs.insert_one({
                            "user_id": ObjectId(current_user),
                            "action": "tts_generate",
                            "timestamp": datetime.utcnow(),
                            "characters_used": job_info.get("text_length", 0),
                            "metadata": {
                                "voice": voice_id,
                                "duration": duration,
                                "plan": plan,
                                "audio_id": audio_id
                            }
                        })
                except Exception as e:
                    logger.error(f"Failed to save audio: {e}")
                    import traceback
                    traceback.print_exc()
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
    current_user: Optional[dict] = Depends(get_current_user_optional),
    audio_service: AudioService = Depends(get_audio_service),
    request: Request = None,
):
    """List user's audio files with pagination (supports anonymous)."""
    # For anonymous users, use session_id header
    session_id = None
    if not current_user:
        session_id = request.headers.get("X-Session-ID") if request else None
    
    user_id = str(current_user["_id"]) if current_user else None
    
    audios, total = await audio_service.list_user_audios(
        user_id=user_id,
        session_id=session_id if not current_user else None,
        page=page,
        per_page=min(per_page, 100)
    )
    
    pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    
    # Convert audio data to AudioResponse format
    from models.schemas.audio import AudioFormat
    items = []
    for a in audios:
        try:
            a["format"] = AudioFormat(a.get("format", "wav"))
            a["user_id"] = str(a.get("user_id", "")) if a.get("user_id") else ""
            items.append(AudioResponse(**a))
        except Exception as e:
            logger.warning(f"Skipping audio item due to format error: {e}")
            continue
    
    return AudioListResponse(
        items=items,
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
    voice_name: str = "",
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Clone a voice from reference audio.
    Requires Plus or Pro plan.
    """
    from services.cloning_service import VoiceCloningService
    
    try:
        cloning_service = VoiceCloningService(get_database())
        
        # Read audio file
        audio_data = await ref_audio.read()
        
        # Create voice clone
        voice_id, voice_data = await cloning_service.create_clone(
            user_id=str(current_user["_id"]),
            audio_data=audio_data,
            voice_name=voice_name or f"Clone {datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        
        logger.info(f"Voice clone created: {voice_id} for user {current_user['_id']}")
        
        return {
            "message": "Voice cloned successfully",
            "status": "completed",
            "voice_id": voice_id,
            "name": voice_data["name"]
        }
        
    except Exception as e:
        logger.error(f"Voice cloning error: {e}")
        return {
            "message": f"Voice cloning failed: {str(e)}",
            "status": "failed",
            "voice_id": None
        }


@router.get(
    "/cloned-voices",
    summary="List cloned voices",
    description="Get list of user's cloned voices.",
)
async def list_cloned_voices(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's cloned voices."""
    from bson import ObjectId
    
    user_id = str(current_user["_id"])
    
    try:
        voices = await db.cloned_voices.find({
            "user_id": ObjectId(user_id)
        }).sort("created_at", -1).to_list(length=100)
        
        return {
            "voices": [
                {
                    "id": str(v["_id"]),
                    "name": v.get("name", "Unnamed"),
                    "created": v.get("created_at", datetime.now()).isoformat()
                }
                for v in voices
            ],
            "total": len(voices)
        }
    except Exception as e:
        logger.error(f"List cloned voices error: {e}")
        return {"voices": [], "total": 0}


@router.delete(
    "/cloned-voices/{voice_id}",
    summary="Delete cloned voice",
    description="Delete a cloned voice.",
)
async def delete_cloned_voice(
    voice_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete a cloned voice."""
    from bson import ObjectId
    
    user_id = str(current_user["_id"])
    
    try:
        result = await db.cloned_voices.delete_one({
            "_id": ObjectId(voice_id),
            "user_id": ObjectId(user_id)
        })
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice not found"
            )
        
        return {"message": "Voice deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete cloned voice error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete voice"
        )


# ===========================================
# Admin Audio Management
# ===========================================

@router.get(
    "/admin/list",
    summary="Admin: List all audio files",
    description="Get paginated list of all audio files across all users (admin only).",
)
async def admin_list_audios(
    page: int = 1,
    per_page: int = 20,
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
):
    """List all audio files with optional filtering (admin only)."""
    # Verify admin
    try:
        from api.dependencies import get_current_admin_user
        await get_current_admin_user(current_user)
    except:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Build query
        query = {}
        if user_id:
            query["user_id"] = ObjectId(user_id)
        
        # Get total count
        total = await db.audio_files.count_documents(query)
        
        # Get paginated results
        skip = (page - 1) * per_page
        cursor = db.audio_files.find(query).sort("created_at", -1).skip(skip).limit(per_page)
        
        audios = []
        async for audio in cursor:
            # Get user info
            user = await db.users.find_one({"_id": audio["user_id"]})
            audio["id"] = str(audio.pop("_id"))
            audio["user_id"] = str(audio["user_id"])
            audio["user_email"] = user.get("email", "Unknown") if user else "Unknown"
            audio["user_name"] = user.get("name", "") if user else ""
            audios.append(audio)
        
        pages = (total + per_page - 1) // per_page if per_page > 0 else 0
        
        return {
            "items": audios,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages
        }
    except Exception as e:
        logger.error(f"Admin list audios error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/stats",
    summary="Admin: Get audio statistics",
    description="Get audio generation statistics (admin only).",
)
async def admin_audio_stats(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get audio generation statistics (admin only)."""
    try:
        # Verify admin
        from api.dependencies import get_current_admin_user
        await get_current_admin_user(current_user)
    except:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Total audios
        total_audios = await db.audio_files.count_documents({})
        
        # Total size
        pipeline_size = [
            {"$group": {"_id": None, "total_size": {"$sum": "$filesize"}}}
        ]
        size_result = await db.audio_files.aggregate(pipeline_size).to_list(length=1)
        total_size = size_result[0]["total_size"] if size_result else 0
        
        # Audios today
        today_start = datetime.now(VIETNAM_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start.astimezone(timezone.utc)
        audios_today = await db.audio_files.count_documents({
            "created_at": {"$gte": today_start_utc}
        })
        
        # Audios by voice
        pipeline_voice = [
            {"$group": {"_id": "$voice_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        voice_stats = await db.audio_files.aggregate(pipeline_voice).to_list(length=10)
        
        # Audios by user (top 10)
        pipeline_user = [
            {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        user_stats = await db.audio_files.aggregate(pipeline_user).to_list(length=10)
        
        # Enrich user stats with email
        enriched_user_stats = []
        for stat in user_stats:
            user = await db.users.find_one({"_id": stat["_id"]})
            enriched_user_stats.append({
                "user_id": str(stat["_id"]),
                "email": user.get("email", "Unknown") if user else "Unknown",
                "count": stat["count"]
            })
        
        return {
            "total_audios": total_audios,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "audios_today": audios_today,
            "by_voice": [{"voice_id": v["_id"], "count": v["count"]} for v in voice_stats],
            "top_users": enriched_user_stats
        }
    except Exception as e:
        logger.error(f"Admin audio stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
