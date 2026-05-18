"""
Smart Chunking Utilities for Vietnamese TTS

Provides intelligent text chunking that:
- Splits by sentence boundaries (not random cuts)
- Dynamically sizes chunks based on sentence length
- Preserves natural Vietnamese pronunciation and pauses
- Maintains stable speaking style across chunks
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Callable
from enum import Enum
import hashlib


class ChunkType(Enum):
    """Type of chunk boundary."""
    SENTENCE_END = "sentence_end"      # Natural sentence ending
    CLAUSE_END = "clause_end"          # Clause separated by comma/semicolon
    ARTIFICIAL = "artificial"          # Manually split (needs pause handling)


@dataclass
class SentenceChunk:
    """A sentence or clause chunk for TTS processing."""
    text: str
    chunk_type: ChunkType
    index: int
    char_count: int = 0
    word_count: int = 0
    estimated_tokens: int = 0

    def __post_init__(self):
        if not self.char_count:
            self.char_count = len(self.text)
        if not self.word_count:
            self.word_count = len(self.text.split())
        # Rough estimate: ~2 tokens per Vietnamese word
        if not self.estimated_tokens:
            self.estimated_tokens = self.word_count * 2


@dataclass
class ChunkGroup:
    """A group of sentences that will be processed together."""
    chunks: List[SentenceChunk] = field(default_factory=list)
    total_chars: int = 0
    total_tokens: int = 0
    total_sentences: int = 0

    def add(self, chunk: SentenceChunk) -> None:
        self.chunks.append(chunk)
        self.total_chars += chunk.char_count
        self.total_tokens += chunk.estimated_tokens
        self.total_sentences += 1

    def get_text(self) -> str:
        """Get concatenated text of all chunks."""
        return " ".join(c.text for c in self.chunks)

    def get_full_text_with_pauses(self) -> str:
        """Get text with appropriate pauses between clauses."""
        parts = []
        for i, chunk in enumerate(self.chunks):
            parts.append(chunk.text)
            # Add pause based on chunk type
            if i < len(self.chunks) - 1:
                if chunk.chunk_type == ChunkType.SENTENCE_END:
                    parts.append(".")  # Full stop
                elif chunk.chunk_type == ChunkType.CLAUSE_END:
                    parts.append(",")  # Comma pause
        return " ".join(parts)


@dataclass
class ChunkConfig:
    """Configuration for smart chunking."""
    # Character limits
    min_chars_per_chunk: int = 50       # Minimum chars for a valid chunk
    max_chars_per_chunk: int = 350      # Hard limit for model
    target_chars_per_chunk: int = 256   # Target for optimal generation

    # Token limits (rough estimate)
    max_tokens_per_chunk: int = 600     # Including prompt overhead

    # Sentence limits
    max_sentences_per_chunk: int = 10   # Maximum sentences in one group
    min_sentences_per_chunk: int = 1    # Minimum sentences

    # Long sentence handling
    long_sentence_threshold: int = 200   # Chars that trigger special handling
    max_long_sentence_chunks: int = 3   # Max chunks to split a long sentence into

    # Short sentence handling
    short_sentence_threshold: int = 80  # Below this, allow more sentences per chunk
    max_short_sentences_per_chunk: int = 15  # Allow more short sentences

    # Performance
    enable_caching: bool = True         # Cache chunk results
    cache_size: int = 1000              # Number of cached chunks


# Vietnamese sentence-ending patterns
RE_SENTENCE_END = re.compile(r'(?<=[.!?…])(?=\s+(?:[A-ZÀ-Ỹ]|$))')
RE_MINOR_CLAUSE = re.compile(r'(?<=[\,\;\:])\s+')
RE_SENTENCE_FINDALL = re.compile(r'[^.!?]+[.!?]*|[.!?]+')
RE_NEWLINE = re.compile(r'[\r\n]+')

# Common Vietnamese abbreviations to protect
_ABBREVIATIONS = {
    'TP.HCM', 'TP.HCM.', 'TP. HCM', 'TP HCM', 'HCM', 'HCM.',
    'Hà Nội', 'Hà Nội.',
    'Ông', 'Ông.', 'Bà', 'Bà.', 'Cô', 'Cô.', 'Chị', 'Chị.',
    'Mr', 'Mr.', 'Mrs', 'Mrs.', 'Ms', 'Ms.', 'Dr', 'Dr.', 'Prof', 'Prof.',
    'Ts', 'Ts.', 'Ths', 'Ths.', 'PGS', 'PGS.', 'GS', 'GS.',
    'V.V.', 'V.V', 'VV', 'VV.',
}

# URL/email detection
RE_URL_EMAIL = re.compile(
    r'(?:https?://|www\.)[^\s<>"\']+|'
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|'
    r'(?<=\s)\d{1,5}[-]\d{1,4}[-]\d{1,4}(?=\s)'
)


def _protect_text(text: str) -> Tuple[str, dict]:
    """Protect URLs, emails, and abbreviations from splitting."""
    placeholders = {}

    # Protect URLs and emails
    def url_replacer(match):
        key = f"__URL_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    text = RE_URL_EMAIL.sub(url_replacer, text)

    return text, placeholders


def _restore_text(text: str, placeholders: dict) -> str:
    """Restore protected content."""
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _split_into_sentences(text: str) -> List[Tuple[str, ChunkType]]:
    """
    Split text into sentences with their types.

    Returns:
        List of (sentence, chunk_type) tuples
    """
    # Handle newlines first - treat as paragraph breaks
    paragraphs = RE_NEWLINE.split(text)
    result = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Find sentence boundaries
        sentences = RE_SENTENCE_FINDALL.findall(para)

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue

            # Determine chunk type based on ending punctuation
            if sent[-1] in '.!?':
                chunk_type = ChunkType.SENTENCE_END
            else:
                chunk_type = ChunkType.CLAUSE_END
                # Add period if missing for natural TTS
                if not sent.endswith((',', ';', ':')):
                    sent = sent + '.'

            result.append((sent, chunk_type))

    return result


def _analyze_sentence(sent: str) -> dict:
    """Analyze sentence characteristics."""
    char_count = len(sent)
    word_count = len(sent.split())

    # Estimate tokens (rough: 1.5x for Vietnamese phonemes)
    estimated_tokens = int(word_count * 1.5)

    # Check if long or short
    is_long = char_count > 200
    is_short = char_count < 80

    # Check complexity (number of clauses)
    clause_count = len(re.findall(r'[,;:]', sent)) + 1

    return {
        'char_count': char_count,
        'word_count': word_count,
        'estimated_tokens': estimated_tokens,
        'is_long': is_long,
        'is_short': is_short,
        'clause_count': clause_count
    }


def smart_chunk_text(
    text: str,
    config: Optional[ChunkConfig] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[ChunkGroup]:
    """
    Intelligently split text into optimal chunks for TTS generation.

    Features:
    - Dynamic chunk sizing based on sentence length
    - Natural sentence boundary preservation
    - Optimal chunk grouping for stable generation
    - Memory-efficient processing

    Args:
        text: Input Vietnamese text
        config: Chunk configuration
        progress_callback: Optional callback(current, total, status)

    Returns:
        List of ChunkGroup objects ready for TTS processing
    """
    if config is None:
        config = ChunkConfig()

    if not text or not text.strip():
        return []

    # Protect special content
    text, placeholders = _protect_text(text)

    # Split into sentences
    sentences = _split_into_sentences(text)

    if not sentences:
        return []

    # Restore protected content in sentences
    sentences = [(s, ct) for s, ct in sentences]
    sentences = [(_restore_text(s, placeholders), ct) for s, ct in sentences]

    # Create chunks
    groups: List[ChunkGroup] = []
    current_group = ChunkGroup()

    total_sentences = len(sentences)

    for idx, (sent, chunk_type) in enumerate(sentences):
        # Report progress
        if progress_callback:
            progress_callback(idx + 1, total_sentences, f"Processing sentence {idx + 1}/{total_sentences}")

        analysis = _analyze_sentence(sent)

        # Check if we need to start a new group
        should_start_new_group = False
        should_split_long_sentence = False

        # Case 1: Current sentence is too long
        if analysis['is_long'] and analysis['char_count'] > config.max_chars_per_chunk:
            should_split_long_sentence = True

        # Case 2: Adding this sentence would exceed limits
        if current_group.total_sentences > 0:
            projected_chars = current_group.total_chars + analysis['char_count']
            projected_tokens = current_group.total_tokens + analysis['estimated_tokens']

            char_exceeds = projected_chars > config.target_chars_per_chunk
            token_exceeds = projected_tokens > config.max_tokens_per_chunk
            sentence_exceeds = current_group.total_sentences >= config.max_sentences_per_chunk

            if char_exceeds or token_exceeds or sentence_exceeds:
                should_start_new_group = True

        # Case 3: Group is empty and we have content
        if not current_group.chunks and current_group.total_chars == 0:
            should_start_new_group = True

        # Handle long sentence splitting
        if should_split_long_sentence:
            # First, save current group if not empty
            if current_group.chunks:
                groups.append(current_group)
                current_group = ChunkGroup()

            # Split long sentence into smaller pieces
            sub_chunks = _split_long_sentence(sent, config)
            for sub in sub_chunks:
                sub_chunk = SentenceChunk(
                    text=sub,
                    chunk_type=ChunkType.ARTIFICIAL,
                    index=idx
                )
                current_group.add(sub_chunk)

                # Check if we need to start new group after adding
                if current_group.total_chars >= config.target_chars_per_chunk:
                    groups.append(current_group)
                    current_group = ChunkGroup()

        elif should_start_new_group:
            # Save current group
            if current_group.chunks:
                groups.append(current_group)
            current_group = ChunkGroup()

            # Create new chunk
            chunk = SentenceChunk(
                text=sent,
                chunk_type=chunk_type,
                index=idx
            )
            current_group.add(chunk)

        else:
            # Add to current group
            chunk = SentenceChunk(
                text=sent,
                chunk_type=chunk_type,
                index=idx
            )
            current_group.add(chunk)

    # Don't forget the last group
    if current_group.chunks:
        groups.append(current_group)

    # Merge very small groups with neighbors
    groups = _merge_small_groups(groups, config)

    return groups


def _split_long_sentence(sent: str, config: ChunkConfig) -> List[str]:
    """
    Split a long sentence into smaller chunks.

    Tries to split at:
    1. Clause separators (comma, semicolon)
    2. Word boundaries near the middle
    3. Random (with minimal damage)
    """
    max_len = config.max_chars_per_chunk - 20  # Buffer

    if len(sent) <= max_len:
        return [sent]

    parts = []

    # Try splitting by clause separators first
    clauses = re.split(r'[,;:]', sent)
    current_part = ""

    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue

        # Add separator back
        sep = ""
        if sent[len(current_part):len(current_part) + len(clause) + 1].endswith(','):
            sep = ","
        elif sent[len(current_part):len(current_part) + len(clause) + 1].endswith(';'):
            sep = ";"
        elif sent[len(current_part):len(current_part) + len(clause) + 1].endswith(':'):
            sep = ":"

        test_part = current_part + (" " if current_part else "") + clause + sep

        if len(test_part) <= max_len:
            current_part = test_part
        else:
            # Current part is full, save it
            if current_part:
                parts.append(current_part.strip())
            current_part = clause + sep

    # Handle remaining
    if current_part.strip():
        if len(current_part) <= max_len:
            parts.append(current_part.strip())
        else:
            # Need to split current part
            remaining = current_part.split()
            current = ""
            for word in remaining:
                test = (current + " " + word).strip()
                if len(test) <= max_len:
                    current = test
                else:
                    if current:
                        parts.append(current)
                    current = word
            if current.strip():
                parts.append(current.strip())

    # If still too long, force split at word boundaries
    final_parts = []
    for part in parts:
        if len(part) <= max_len:
            final_parts.append(part)
        else:
            # Split at word boundary
            words = part.split()
            current = ""
            for word in words:
                test = (current + " " + word).strip()
                if len(test) <= max_len:
                    current = test
                else:
                    if current:
                        final_parts.append(current)
                    # If single word is too long, force split
                    if len(word) > max_len:
                        for i in range(0, len(word), max_len - 10):
                            final_parts.append(word[i:i + max_len - 10])
                    else:
                        current = word
            if current.strip():
                final_parts.append(current.strip())

    # Remove empty parts and ensure all are within limits
    final_parts = [p.strip() for p in final_parts if p.strip()]
    final_parts = [p[:max_len] for p in final_parts]

    # Ensure we have at least one part
    if not final_parts:
        final_parts = [sent[:max_len]]

    return final_parts


def _merge_small_groups(groups: List[ChunkGroup], config: ChunkConfig) -> List[ChunkGroup]:
    """
    Merge very small groups with neighbors to optimize generation.

    Groups smaller than min_chars_per_chunk are merged with adjacent groups.
    """
    if len(groups) <= 1:
        return groups

    min_size = config.min_chars_per_chunk // 2
    merged = []
    skip_next = False

    for i, group in enumerate(groups):
        if skip_next:
            skip_next = False
            continue

        # Check if group is too small
        if group.total_chars < min_size:
            # Try to merge with next group
            if i + 1 < len(groups):
                next_group = groups[i + 1]
                combined_chars = group.total_chars + next_group.total_chars

                if combined_chars <= config.target_chars_per_chunk * 1.2:
                    # Merge with next
                    for chunk in next_group.chunks:
                        group.add(chunk)
                    merged.append(group)
                    skip_next = True
                    continue

            # Try to merge with previous group
            if merged:
                prev_group = merged[-1]
                combined_chars = prev_group.total_chars + group.total_chars

                if combined_chars <= config.target_chars_per_chunk * 1.2:
                    # Merge with previous
                    for chunk in group.chunks:
                        prev_group.add(chunk)
                    continue

        merged.append(group)

    return merged if merged else groups


def get_chunk_hash(text: str, voice_id: str = None) -> str:
    """Generate a hash for chunk caching."""
    voice_suffix = voice_id or ""
    content = f"{text}|{voice_suffix}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]


class ChunkCache:
    """LRU cache for chunk results."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: dict = {}
        self._access_order: List[str] = []

    def get(self, key: str) -> Optional[any]:
        if key in self._cache:
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: any) -> None:
        if key in self._cache:
            self._access_order.remove(key)
        elif len(self._cache) >= self.max_size:
            # Remove least recently used
            lru_key = self._access_order.pop(0)
            del self._cache[lru_key]

        self._cache[key] = value
        self._access_order.append(key)

    def clear(self) -> None:
        self._cache.clear()
        self._access_order.clear()


# Global cache instance
_chunk_cache = ChunkCache()


def get_chunk_cache() -> ChunkCache:
    """Get the global chunk cache instance."""
    return _chunk_cache
