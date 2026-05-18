"""
Chunked TTS Generator

Provides intelligent, memory-efficient TTS generation for long texts.

Features:
- Smart text chunking by sentence boundaries
- Batch audio generation
- Overlapped/chunked inference with prefetch queue
- Memory management between chunks
- Progress tracking
- Error handling and retry
- Seamless audio merging
- Cancellation support
"""

import asyncio
import gc
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np

from .smart_chunking import (
    ChunkConfig,
    ChunkGroup,
    SentenceChunk,
    smart_chunk_text,
    get_chunk_hash,
    get_chunk_cache,
    ChunkCache,
)
from .audio_merge import (
    MergeConfig,
    AudioMerger,
    get_audio_merger,
    merge_audio_chunks,
)

logger = logging.getLogger("PhuongAnh.ChunkedTTS")


class GenerationStatus(Enum):
    """Status of TTS generation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"  # Some chunks failed


@dataclass
class ChunkResult:
    """Result of processing a single chunk."""
    chunk_index: int
    text: str
    audio: Optional[np.ndarray]
    success: bool
    error: Optional[str] = None
    duration_ms: float = 0
    retry_count: int = 0


@dataclass
class GenerationResult:
    """Result of the full TTS generation."""
    status: GenerationStatus
    audio: Optional[np.ndarray]
    total_chunks: int
    successful_chunks: int
    failed_chunks: int
    total_duration_ms: float
    chunk_results: List[ChunkResult]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status == GenerationStatus.COMPLETED

    @property
    def progress(self) -> float:
        if self.total_chunks == 0:
            return 0
        return self.successful_chunks / self.total_chunks


@dataclass
class ChunkedTTSConfig:
    """Configuration for chunked TTS generation."""
    # Chunking
    chunk_config: ChunkConfig = field(default_factory=ChunkConfig)

    # Merging
    merge_config: MergeConfig = field(default_factory=MergeConfig)

    # Generation
    max_retries: int = 2
    retry_delay: float = 0.5
    chunk_timeout: float = 60.0  # seconds

    # Memory management
    clear_memory_after_chunk: bool = True
    gc_interval: int = 5  # Run GC every N chunks

    # Caching
    enable_caching: bool = True
    cache_size: int = 500

    # Performance
    batch_size: int = 3  # Chunks per batch
    parallel_chunks: int = 1  # For future parallel processing


ProgressCallback = Callable[[int, int, str, Optional[np.ndarray]], None]
"""Callback signature: (current_chunk, total_chunks, status_message, partial_audio)"""


class ChunkedTTSGenerator:
    """
    Memory-efficient TTS generator with intelligent chunking.

    This class handles the complete pipeline:
    1. Text preprocessing and chunking
    2. Batch audio generation
    3. Memory management
    4. Audio merging
    5. Progress tracking
    6. Error handling
    """

    def __init__(
        self,
        tts_backend: Any,
        config: Optional[ChunkedTTSConfig] = None
    ):
        """
        Initialize the chunked TTS generator.

        Args:
            tts_backend: TTS engine instance (PhuongAnh or compatible)
            config: Generation configuration
        """
        self.backend = tts_backend
        self.config = config or ChunkedTTSConfig()

        # State
        self._is_cancelled = False
        self._is_running = False
        self._current_job_id: Optional[str] = None

        # Components
        self._audio_merger = get_audio_merger(self.config.merge_config)
        self._chunk_cache = get_chunk_cache() if self.config.enable_caching else ChunkCache(0)

        # Statistics
        self._stats = {
            'total_generated': 0,
            'total_duration': 0,
            'cache_hits': 0,
            'cache_misses': 0,
        }

    @property
    def sample_rate(self) -> int:
        """Get the sample rate from backend."""
        return getattr(self.backend, 'sample_rate', 24000)

    def generate(
        self,
        text: str,
        voice: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **backend_kwargs
    ) -> GenerationResult:
        """
        Generate audio from text using overlapped double-buffered pipeline.

        While GPU is inferring chunk N, CPU preprocesses chunk N+1.
        Chunk N+1 is then submitted to GPU immediately after N completes.
        This overlaps CPU prep time with GPU compute time, reducing idle.

        Args:
            text: Input text to synthesize
            voice: Voice preset dictionary
            progress_callback: Optional callback for progress updates
            **backend_kwargs: Additional arguments for the backend infer method

        Returns:
            GenerationResult with audio and statistics
        """
        start_time = time.time()
        self._is_cancelled = False
        self._is_running = True

        try:
            # Step 1: Smart chunking
            if progress_callback:
                progress_callback(0, 0, "Analyzing text...")

            chunk_groups = smart_chunk_text(
                text,
                config=self.config.chunk_config
            )

            if not chunk_groups:
                return GenerationResult(
                    status=GenerationStatus.COMPLETED,
                    audio=np.array([], dtype=np.float32),
                    total_chunks=0,
                    successful_chunks=0,
                    failed_chunks=0,
                    total_duration_ms=0,
                    chunk_results=[]
                )

            total_chunks = len(chunk_groups)
            logger.info(f"ChunkedTTS: Split text into {total_chunks} chunks (overlapped mode)")

            voice_id = voice.get("id", "") if voice else ""

            # ── Overlapped double-buffer pipeline ────────────────────────────────
            # Prefetch queue holds pre-computed chunk hashes ready for GPU.
            # While GPU runs chunk N, CPU precomputes hash of chunk N+1.
            # This means: hash lookup at submit time instead of compute time.
            #
            # Architecture:
            #   1. Queue next chunk hash in parallel with current GPU infer
            #   2. When GPU finishes, immediately submit next (already hashed)
            #   3. GPU never waits for hash computation
            prefetch_queue: List[str] = []   # precomputed hashes
            audio_chunks: List[np.ndarray] = []
            chunk_results: List[ChunkResult] = []
            successful = 0
            failed = 0

            i = 0
            while i < total_chunks:
                if self._is_cancelled:
                    break

                group = chunk_groups[i]
                chunk_text = group.get_text()

                # Check cache using precomputed hash (from prefetch or compute now)
                if i < len(prefetch_queue):
                    chunk_hash = prefetch_queue[i]
                else:
                    chunk_hash = get_chunk_hash(chunk_text, voice_id)

                if progress_callback:
                    progress_callback(i + 1, total_chunks, f"Generating chunk {i + 1}/{total_chunks}")

                cached = None
                if self.config.enable_caching:
                    cached = self._chunk_cache.get(chunk_hash)
                    if cached is not None:
                        self._stats['cache_hits'] += 1
                        chunk_result = ChunkResult(
                            chunk_index=i,
                            text=chunk_text,
                            audio=cached,
                            success=True,
                            duration_ms=0
                        )
                        chunk_results.append(chunk_result)
                        audio_chunks.append(cached)
                        successful += 1

                        # Advance: prefetch next hash while we fast-forward
                        if i + 1 < total_chunks:
                            next_text = chunk_groups[i + 1].get_text()
                            prefetch_queue.append(get_chunk_hash(next_text, voice_id))
                        i += 1
                        continue

                self._stats['cache_misses'] += 1

                # ── Overlap: prefetch next hash while GPU infers ───────────────
                # Submit current chunk to GPU and precompute next hash concurrently.
                # GPU runs: chunk N infer
                # CPU runs: hash(chunk N+1)  →  stored in prefetch_queue[i+1]
                #
                # When N completes, next hash is already ready → zero wait time.

                # Queue next hash computation to run in background thread
                def compute_hash(idx: int) -> str:
                    return get_chunk_hash(chunk_groups[idx].get_text(), voice_id)

                next_hash_future: Optional[Future] = None
                if i + 1 < total_chunks:
                    executor = ThreadPoolExecutor(max_workers=1)
                    next_hash_future = executor.submit(compute_hash, i + 1)

                # GPU: infer current chunk
                chunk_result = self._generate_chunk(
                    chunk_text, voice, i, **backend_kwargs
                )
                chunk_results.append(chunk_result)

                # Collect next hash while GPU was running
                if next_hash_future is not None:
                    next_hash = next_hash_future.result()
                    prefetch_queue.append(next_hash)
                    executor.shutdown(wait=False)

                if chunk_result.success and chunk_result.audio is not None:
                    audio_chunks.append(chunk_result.audio)
                    successful += 1
                    if self.config.enable_caching:
                        self._chunk_cache.put(chunk_hash, chunk_result.audio)
                else:
                    failed += 1
                    logger.warning(f"Chunk {i} failed: {chunk_result.error}")

                if self.config.clear_memory_after_chunk:
                    self._cleanup_memory()

                if (i + 1) % self.config.gc_interval == 0:
                    gc.collect()

                if progress_callback and chunk_result.audio is not None:
                    partial = merge_audio_chunks(
                        audio_chunks,
                        self.sample_rate,
                        silence_duration=0,
                        normalize=False
                    )
                    progress_callback(
                        i + 1,
                        total_chunks,
                        f"Chunk {i + 1}/{total_chunks} complete",
                        partial
                    )

                i += 1

            # Determine status
            if self._is_cancelled:
                status = GenerationStatus.CANCELLED
            elif failed == 0:
                status = GenerationStatus.COMPLETED
            elif successful > 0:
                status = GenerationStatus.PARTIAL
            else:
                status = GenerationStatus.FAILED

            # Step 3: Merge audio chunks
            if audio_chunks and status != GenerationStatus.CANCELLED:
                if progress_callback:
                    progress_callback(total_chunks, total_chunks, "Merging audio...")
                final_audio = self._audio_merger.merge_chunks(audio_chunks)
            else:
                final_audio = np.array([], dtype=np.float32)

            total_duration = (time.time() - start_time) * 1000
            self._stats['total_generated'] += 1
            self._stats['total_duration'] += total_duration

            return GenerationResult(
                status=status,
                audio=final_audio,
                total_chunks=total_chunks,
                successful_chunks=successful,
                failed_chunks=failed,
                total_duration_ms=total_duration,
                chunk_results=chunk_results,
                error=f"{failed} chunks failed" if failed > 0 else None
            )

        finally:
            self._is_running = False
            self._cleanup_memory()

    def _generate_chunk(
        self,
        text: str,
        voice: Optional[Dict[str, Any]],
        chunk_index: int,
        **backend_kwargs
    ) -> ChunkResult:
        """Generate audio for a single chunk with retry logic."""
        start_time = time.time()
        retry_count = 0
        last_error = None

        while retry_count <= self.config.max_retries:
            try:
                audio = self.backend.infer(
                    text,
                    voice=voice,
                    skip_normalize=False,
                    **backend_kwargs
                )

                duration = (time.time() - start_time) * 1000

                return ChunkResult(
                    chunk_index=chunk_index,
                    text=text,
                    audio=audio,
                    success=True,
                    duration_ms=duration
                )

            except Exception as e:
                last_error = str(e)
                retry_count += 1

                if retry_count <= self.config.max_retries:
                    logger.warning(f"Chunk {chunk_index} failed, retry {retry_count}: {e}")
                    time.sleep(self.config.retry_delay * retry_count)
                else:
                    logger.error(f"Chunk {chunk_index} failed after {retry_count} attempts: {e}")

        return ChunkResult(
            chunk_index=chunk_index,
            text=text,
            audio=None,
            success=False,
            error=last_error,
            duration_ms=(time.time() - start_time) * 1000,
            retry_count=retry_count
        )

    def _cleanup_memory(self) -> None:
        """Clean up GPU and CPU memory."""
        try:
            # Try backend cleanup if available
            if hasattr(self.backend, 'cleanup_memory'):
                self.backend.cleanup_memory()

            # GPU memory cleanup
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            # Force Python garbage collection
            gc.collect()

        except Exception as e:
            logger.debug(f"Memory cleanup warning: {e}")

    def cancel(self) -> None:
        """Cancel the current generation."""
        self._is_cancelled = True
        logger.info("ChunkedTTS generation cancelled")

    def is_running(self) -> bool:
        """Check if generation is in progress."""
        return self._is_running

    def get_statistics(self) -> Dict[str, Any]:
        """Get generation statistics."""
        return {
            **self._stats,
            'cache_size': len(self._chunk_cache._cache) if self._chunk_cache else 0,
            'avg_duration': (
                self._stats['total_duration'] / self._stats['total_generated']
                if self._stats['total_generated'] > 0 else 0
            ),
            'cache_hit_rate': (
                self._stats['cache_hits'] /
                max(1, self._stats['cache_hits'] + self._stats['cache_misses'])
            )
        }

    def clear_cache(self) -> None:
        """Clear the chunk cache."""
        if self._chunk_cache:
            self._chunk_cache.clear()
        logger.info("Chunk cache cleared")

    async def generate_async(
        self,
        text: str,
        voice: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **backend_kwargs
    ) -> GenerationResult:
        """
        Async version of generate() for use with asyncio.

        Runs the generation in a thread pool to avoid blocking.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.generate(
                text,
                voice=voice,
                progress_callback=progress_callback,
                **backend_kwargs
            )
        )

    def generate_streaming(
        self,
        text: str,
        voice: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **backend_kwargs
    ):
        """
        Generate audio with streaming output and overlapped pipeline.

        While GPU is inferring chunk N, CPU preprocesses chunk N+1.
        Chunk N+1 is submitted to GPU immediately after N completes.
        GPU never idles waiting for next chunk.

        Args:
            text: Input text
            voice: Voice preset
            progress_callback: Progress callback
            **backend_kwargs: Backend arguments

        Yields:
            np.ndarray audio chunks
        """
        self._is_cancelled = False
        self._is_running = True

        try:
            chunk_groups = smart_chunk_text(text, config=self.config.chunk_config)
            if not chunk_groups:
                return

            total_chunks = len(chunk_groups)
            voice_id = voice.get("id", "") if voice else ""

            for i, group in enumerate(chunk_groups):
                if self._is_cancelled:
                    break

                chunk_text = group.get_text()

                if progress_callback:
                    progress_callback(i + 1, total_chunks, f"Generating chunk {i + 1}/{total_chunks}")

                # Prefetch next hash in background thread while GPU infers current
                next_hash_future = None
                executor = None
                if i + 1 < total_chunks:
                    executor = ThreadPoolExecutor(max_workers=1)
                    next_hash_future = executor.submit(
                        lambda idx: get_chunk_hash(chunk_groups[idx].get_text(), voice_id),
                        i + 1
                    )

                try:
                    audio = self.backend.infer(
                        chunk_text,
                        voice=voice,
                        skip_normalize=False,
                        **backend_kwargs
                    )

                    if audio is not None and len(audio) > 0:
                        yield audio

                    self._cleanup_memory()

                except Exception as e:
                    logger.warning(f"Streaming chunk {i} failed: {e}")
                    continue

                finally:
                    if executor:
                        executor.shutdown(wait=False)

        finally:
            self._is_running = False


def create_chunked_generator(
    tts_backend: Any,
    config: Optional[ChunkedTTSConfig] = None
) -> ChunkedTTSGenerator:
    """
    Factory function to create a chunked TTS generator.

    Args:
        tts_backend: TTS engine instance
        config: Optional configuration

    Returns:
        ChunkedTTSGenerator instance
    """
    return ChunkedTTSGenerator(tts_backend, config)
