"""
phuonganh_utils — Text processing and audio utilities for phuonganh-tts.

Provides:
- phonemize_text: Vietnamese G2P and text normalization
- core_utils: Text chunking, audio joining, silence handling
- url_extract: Web scraping for training data
"""
from phuonganh_utils.phonemize_text import (
    phonemize_text,
    phonemize_batch,
    phonemize_with_dict,
)
from phuonganh_utils.core_utils import (
    split_text_into_chunks,
    split_into_chunks_v2,
    join_audio_chunks,
    get_silence_duration_v2,
    _clean_phoneme_noise,
)

__all__ = [
    "phonemize_text",
    "phonemize_batch",
    "phonemize_with_dict",
    "split_text_into_chunks",
    "split_into_chunks_v2",
    "join_audio_chunks",
    "get_silence_duration_v2",
    "_clean_phoneme_noise",
]
