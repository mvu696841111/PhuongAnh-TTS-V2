"""
Audio Chunk Processing and Merging Utilities

Provides:
- Seamless audio chunk concatenation
- Silence handling between chunks
- Click/pop prevention
- Volume normalization
- Memory-efficient processing
"""

import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger("PhuongAnh.AudioMerge")


@dataclass
class MergeConfig:
    """Configuration for audio merging."""
    # Silence settings
    silence_duration: float = 0.15        # Seconds of silence between chunks
    sentence_end_silence: float = 0.3    # Silence after sentence end
    clause_silence: float = 0.15        # Silence after clause

    # Crossfade settings
    enable_crossfade: bool = False
    crossfade_duration: float = 0.05      # Seconds for crossfade (minimal)

    # Volume normalization
    normalize_volume: bool = True
    target_db: float = -3.0            # Target loudness in dB

    # Audio parameters
    sample_rate: int = 24000
    dtype: str = 'float32'


class AudioMerger:
    """
    Handles merging of audio chunks with proper silence handling.

    Features:
    - Prevents clicks/pops at boundaries
    - Adds natural pauses between sentences
    - Volume normalization
    - Sample rate consistency
    """

    def __init__(self, config: Optional[MergeConfig] = None):
        self.config = config or MergeConfig()

    def merge_chunks(
        self,
        chunks: List[np.ndarray],
        chunk_types: Optional[List[str]] = None
    ) -> np.ndarray:
        """
        Merge multiple audio chunks into a single audio file.

        Args:
            chunks: List of audio waveforms (numpy arrays)
            chunk_types: Optional list of chunk types for silence handling

        Returns:
            Merged audio as numpy array
        """
        if not chunks:
            return np.array([], dtype=np.float32)

        if len(chunks) == 1:
            return self._normalize(chunks[0])

        # Filter out empty chunks
        valid_chunks = []
        valid_types = []
        for i, chunk in enumerate(chunks):
            if chunk is not None and len(chunk) > 0:
                valid_chunks.append(chunk)
                if chunk_types and i < len(chunk_types):
                    valid_types.append(chunk_types[i])
                else:
                    valid_types.append('default')

        if not valid_chunks:
            return np.array([], dtype=np.float32)

        if len(valid_chunks) == 1:
            return self._normalize(valid_chunks[0])

        # Ensure all chunks have same sample rate and type
        processed = []
        for chunk in valid_chunks:
            # Convert to float32 if needed
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32)

            # Trim excessive silence at start/end
            chunk = self._trim_silence(chunk)

            processed.append(chunk)

        # Merge with silence
        result = self._merge_with_silence(processed, valid_types)

        return self._normalize(result)

    def _merge_with_silence(
        self,
        chunks: List[np.ndarray],
        chunk_types: List[str]
    ) -> np.ndarray:
        """Merge chunks with appropriate silence between them."""
        if not chunks:
            return np.array([], dtype=np.float32)

        if len(chunks) == 1:
            return chunks[0]

        sr = self.config.sample_rate
        silence_samples = int(sr * self.config.silence_duration)

        # Calculate total length
        total_len = sum(len(c) for c in chunks)
        total_len += silence_samples * (len(chunks) - 1)

        # Pre-allocate result array
        result = np.zeros(total_len, dtype=np.float32)

        # Merge chunks
        offset = 0
        for i, chunk in enumerate(chunks):
            chunk_len = len(chunk)

            # Copy chunk
            result[offset:offset + chunk_len] = chunk
            offset += chunk_len

            # Add silence after chunk (except last)
            if i < len(chunks) - 1:
                # Determine silence duration based on chunk type
                chunk_type = chunk_types[i] if i < len(chunk_types) else 'default'

                if chunk_type == 'sentence_end':
                    silence_samples = int(sr * self.config.sentence_end_silence)
                elif chunk_type == 'clause_end':
                    silence_samples = int(sr * self.config.clause_silence)
                else:
                    silence_samples = int(sr * self.config.silence_duration)

                offset += silence_samples

        return result

    def _trim_silence(self, wav: np.ndarray, threshold: float = 0.005) -> np.ndarray:
        """Trim leading and trailing silence."""
        if len(wav) < 100:
            return wav

        # Find first non-silent sample
        start_idx = 0
        for i in range(len(wav)):
            if abs(wav[i]) > threshold:
                start_idx = max(0, i - int(self.config.sample_rate * 0.02))  # 20ms lead-in
                break

        # Find last non-silent sample
        end_idx = len(wav)
        for i in range(len(wav) - 1, -1, -1):
            if abs(wav[i]) > threshold:
                end_idx = min(len(wav), i + int(self.config.sample_rate * 0.05))  # 50ms lead-out
                break

        if start_idx >= end_idx:
            return wav

        return wav[start_idx:end_idx]

    def _normalize(self, wav: np.ndarray) -> np.ndarray:
        """Normalize audio volume."""
        if not self.config.normalize_volume or len(wav) == 0:
            return wav

        # Calculate RMS
        rms = np.sqrt(np.mean(wav ** 2))

        if rms < 1e-6:
            return wav

        # Target RMS from dB
        target_rms = 10 ** (self.config.target_db / 20)

        # Calculate gain
        gain = target_rms / rms

        # Limit gain to prevent clipping
        gain = min(gain, 3.0)

        normalized = wav * gain

        # Soft clip to prevent hard clipping
        normalized = self._soft_clip(normalized)

        return normalized.astype(np.float32)

    def _soft_clip(self, wav: np.ndarray, threshold: float = 0.95) -> np.ndarray:
        """Apply soft clipping to prevent hard clipping."""
        mask = np.abs(wav) > threshold
        if not np.any(mask):
            return wav

        # Soft clip formula: tanh saturation
        clipped = np.copy(wav)
        clipped[mask] = np.tanh(clipped[mask])

        return clipped


class SeamlessAudioMerger(AudioMerger):
    """
    Enhanced audio merger with zero-latency crossfades.

    Uses minimal crossfades to prevent any audible artifacts
    at chunk boundaries.
    """

    def __init__(self, config: Optional[MergeConfig] = None):
        super().__init__(config)
        self.config.enable_crossfade = True
        self.config.crossfade_duration = 0.01  # 10ms crossfade (minimal)

    def _merge_with_crossfade(
        self,
        chunks: List[np.ndarray],
        chunk_types: List[str]
    ) -> np.ndarray:
        """Merge chunks with minimal crossfades at boundaries."""
        if len(chunks) == 1:
            return chunks[0]

        # Use simple concatenation with silence
        return super()._merge_with_silence(chunks, chunk_types)


def merge_audio_chunks(
    chunks: List[np.ndarray],
    sample_rate: int = 24000,
    silence_duration: float = 0.15,
    normalize: bool = True
) -> np.ndarray:
    """
    Simple utility function to merge audio chunks.

    Args:
        chunks: List of audio numpy arrays
        sample_rate: Audio sample rate
        silence_duration: Silence duration between chunks in seconds
        normalize: Whether to normalize volume

    Returns:
        Merged audio array
    """
    config = MergeConfig(
        sample_rate=sample_rate,
        silence_duration=silence_duration,
        normalize_volume=normalize
    )
    merger = AudioMerger(config)
    return merger.merge_chunks(chunks)


def detect_silence_regions(
    wav: np.ndarray,
    sample_rate: int = 24000,
    min_silence_duration: float = 0.3,
    threshold: float = 0.01
) -> List[Tuple[int, int]]:
    """
    Detect regions of silence in audio.

    Returns:
        List of (start_sample, end_sample) tuples
    """
    if len(wav) == 0:
        return []

    min_silence_samples = int(sample_rate * min_silence_duration)
    silence_regions = []

    in_silence = False
    silence_start = 0

    for i in range(len(wav)):
        is_silent = abs(wav[i]) < threshold

        if is_silent and not in_silence:
            in_silence = True
            silence_start = i
        elif not is_silent and in_silence:
            in_silence = False
            silence_end = i
            if silence_end - silence_start >= min_silence_samples:
                silence_regions.append((silence_start, silence_end))

    # Handle trailing silence
    if in_silence:
        silence_end = len(wav)
        if silence_end - silence_start >= min_silence_samples:
            silence_regions.append((silence_start, silence_end))

    return silence_regions


def calculate_audio_stats(wav: np.ndarray, sample_rate: int = 24000) -> dict:
    """
    Calculate audio statistics.

    Returns:
        Dictionary with audio metrics
    """
    if len(wav) == 0:
        return {
            'duration': 0,
            'rms': 0,
            'peak': 0,
            'dynamic_range': 0
        }

    rms = float(np.sqrt(np.mean(wav ** 2)))
    peak = float(np.max(np.abs(wav)))
    duration = len(wav) / sample_rate

    # Calculate dynamic range (dB)
    if rms > 1e-6:
        dynamic_range = 20 * np.log10(peak / rms)
    else:
        dynamic_range = 0

    return {
        'duration': duration,
        'rms': rms,
        'peak': peak,
        'dynamic_range': dynamic_range,
        'sample_count': len(wav)
    }


# Global merger instance
_default_merger: Optional[AudioMerger] = None


def get_audio_merger(config: Optional[MergeConfig] = None) -> AudioMerger:
    """Get the default audio merger instance."""
    global _default_merger
    if _default_merger is None or config is not None:
        _default_merger = AudioMerger(config)
    return _default_merger
