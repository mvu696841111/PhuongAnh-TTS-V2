"""
Re-export audio_merge from phuonganh_utils for backwards compatibility.
"""

from phuonganh_utils.audio_merge import (
    MergeConfig,
    AudioMerger,
    SeamlessAudioMerger,
    get_audio_merger,
    merge_audio_chunks,
    calculate_audio_stats,
    detect_silence_regions,
)

__all__ = [
    'MergeConfig',
    'AudioMerger',
    'SeamlessAudioMerger',
    'get_audio_merger',
    'merge_audio_chunks',
    'calculate_audio_stats',
    'detect_silence_regions',
]
