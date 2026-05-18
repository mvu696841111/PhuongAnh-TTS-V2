"""
Re-export smart_chunking from phuonganh_utils for backwards compatibility.
"""

from phuonganh_utils.smart_chunking import (
    ChunkConfig,
    ChunkGroup,
    SentenceChunk,
    smart_chunk_text,
    get_chunk_hash,
    get_chunk_cache,
    ChunkCache,
)

__all__ = [
    'ChunkConfig',
    'ChunkGroup',
    'SentenceChunk',
    'smart_chunk_text',
    'get_chunk_hash',
    'get_chunk_cache',
    'ChunkCache',
]
