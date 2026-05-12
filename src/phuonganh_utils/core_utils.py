import re
import os
from dataclasses import dataclass
from typing import List, Tuple, Optional

import numpy as np

# ─── Regex ───────────────────────────────────────────────────────────────────

RE_NEWLINE          = re.compile(r'[\r\n]+')  # dùng chung cho cả v1 và v2
RE_SENTENCE_FINDALL = re.compile(r'[^.!?]+[.!?]*|[.!?]+')

# v1 only - Improved patterns for Vietnamese
# Better sentence ending: must have space/newline after .!? and not part of abbreviations
# Also matches when followed by __ABBREV_ or __PROTECTED_ (placeholders)
RE_SENTENCE_END = re.compile(r'(?<=[.!?…])(?=\s+(?:[A-ZÀ-Ỹ_]|$))')
# Minor punctuation: split on comma/semicolon/colon/dash only when followed by space
# But NOT when inside URLs, emails, numbers, or abbreviations
RE_MINOR_PUNCT  = re.compile(r'(?<=[\,\;\:])\s+')
RE_MINOR_DASH   = re.compile(r'(?<=[A-Za-zÀ-ỹ0-9])-(?=\s+[A-Za-zÀ-ỹ])')

# Common Vietnamese abbreviations that should be protected from sentence-end splitting
# These are specific abbreviations, NOT general patterns
_PROTECT_ABBREVIATIONS = {
    'TP.HCM', 'TP.HCM.', 'TP. HCM', 'TP HCM',
    'HCM', 'HCM.', 
    'Hà Nội', 'Hà Nội.', 
    'Ông', 'Ông.', 'Bà', 'Bà.', 'Cô', 'Cô.', 'Chị', 'Chị.',
    'Mr', 'Mr.', 'Mrs', 'Mrs.', 'Ms', 'Ms.', 'Dr', 'Dr.', 'Prof', 'Prof.',
    'Ts', 'Ts.', 'Ths', 'Ths.', 'PGS', 'PGS.', 'GS', 'GS.',
    'ĐH', 'ĐH.', 'THPT', 'THPT.', 'THCS', 'THCS.',
    'V.V.', 'V.V', 'VV', 'VV.',
}

# Pattern for specific Vietnamese/English abbreviations
# Only matches known abbreviations that should NOT be treated as sentence endings
# Key rules:
# - Abbreviations WITH period (like Mr., Dr., Ông.) must be followed by space or end
# - Abbreviations WITHOUT period (like TP.HCM, HCM, Hà Nội) must be followed by a name (lowercase letters)
_RE_TITLE_ABBREV = re.compile(
    # With period - must be at word boundary and followed by space/end
    r'(?<![a-zA-Zà-ỹ])'
    r'(?:TP\.?H?CM|Mr|Mrs|Ms|Dr|Prof|Ts|Ths|PGS|GS|ĐH|THPT|THCS|V\.?V\.?)'
    r'\.(?=\s|$|[.!?])'
    r'|'
    # Without period - specific known abbreviations followed by lowercase name
    r'(?<![a-zA-Zà-ỹ])'
    r'(?:TP\.?H?CM|HCM)'
    r'(?=\s+[a-zà-ỹ])'
    r'|'
    r'(?<![a-zA-Zà-ỹ])'
    r'(?:Hà\s+[Nn]ội)'
    r'(?=\s+[a-zà-ỹ]|$)'
    r'|'
    r'(?<![a-zA-Zà-ỹ])'
    r'(?:Ông|Bà|Cô|Chị|Em)'
    r'(?=\s+[a-zà-ỹ])'
    r'|'
    r'(?<![a-zA-Zà-ỹ])'
    r'Anh'
    r'(?=\s+[a-zà-ỹ])'
    ,
    re.IGNORECASE
)

# URL/email detection to protect them from splitting
RE_URL_EMAIL = re.compile(
    r'(?:https?://|www\.)[^\s<>"\']+|'
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|'
    r'(?<=\s)\d{1,5}[-]\d{1,4}[-]\d{1,4}(?=\s)'  # phone numbers like 0123-456-789
)

# v2 noise cleanup
_NOISE_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'([.!?])[.,;:]+'), r'\1'),
    (re.compile(r'[.,;:]+([.!?])'), r'\1'),
    (re.compile(r'\s+[,;]\s+'),     ' '),
    (re.compile(r' {2,}'),          ' '),
]
_MULTI_PUNCT = re.compile(r'([.!?])\s*[.!?]+')

# ─── Data class ──────────────────────────────────────────────────────────────

@dataclass
class PhoneChunk:
    text: str
    is_sentence_end: bool  # True = kết thúc câu thật | False = cắt nhân tạo

# ─── Audio utils ─────────────────────────────────────────────────────────────

def join_audio_chunks(
    chunks: List[np.ndarray],
    sr: int,
    silence_p: float = 0.0,
    crossfade_p: float = 0.0,
) -> np.ndarray:
    if not chunks:
        return np.array([], dtype=np.float32)
    if len(chunks) == 1:
        return chunks[0]

    silence_samples   = int(sr * silence_p)
    crossfade_samples = int(sr * crossfade_p)
    final_wav = chunks[0]

    for i in range(1, len(chunks)):
        next_chunk = chunks[i]
        if silence_samples > 0:
            silence   = np.zeros(silence_samples, dtype=np.float32)
            final_wav = np.concatenate([final_wav, silence, next_chunk])
        elif crossfade_samples > 0:
            overlap = min(len(final_wav), len(next_chunk), crossfade_samples)
            if overlap > 0:
                fade_out  = np.linspace(1.0, 0.0, overlap, dtype=np.float32)
                fade_in   = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
                blended   = final_wav[-overlap:] * fade_out + next_chunk[:overlap] * fade_in
                final_wav = np.concatenate([final_wav[:-overlap], blended, next_chunk[overlap:]])
            else:
                final_wav = np.concatenate([final_wav, next_chunk])
        else:
            final_wav = np.concatenate([final_wav, next_chunk])

    return final_wav

# ─── v1: split raw text ──────────────────────────────────────────────────────

def _protect_urls_and_emails(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Temporarily replace URLs and emails with placeholders to protect them from splitting.
    Returns (masked_text, list_of_(placeholder, original) pairs).
    """
    placeholders = []
    def replacer(match):
        placeholder = f"__PROTECTED_URL_{len(placeholders)}__"
        placeholders.append((placeholder, match.group(0)))
        return placeholder
    masked = RE_URL_EMAIL.sub(replacer, text)
    return masked, placeholders


def _restore_urls_and_emails(text: str, placeholders: List[Tuple[str, str]]) -> str:
    """Restore URLs and emails from placeholders."""
    for placeholder, original in placeholders:
        text = text.replace(placeholder, original)
    return text


def _protect_abbreviations(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Temporarily protect Vietnamese abbreviations from being treated as sentence endings.
    Returns (masked_text, list_of_(placeholder, original) pairs).
    """
    placeholders = []
    
    def replacer(match):
        original = match.group(0)
        # Skip if it looks like an actual sentence ending (followed by space and capital letter)
        # or if it's part of a protected URL
        if original.startswith("__PROTECTED_"):
            return original
        placeholder = f"__ABBREV_{len(placeholders)}__"
        placeholders.append((placeholder, original))
        return placeholder
    
    masked = _RE_TITLE_ABBREV.sub(replacer, text)
    return masked, placeholders


def _restore_abbreviations(text: str, placeholders: List[Tuple[str, str]]) -> str:
    """Restore abbreviations from placeholders."""
    for placeholder, original in placeholders:
        text = text.replace(placeholder, original)
    return text


def split_text_into_chunks(text: str, max_chars: int = 256) -> List[str]:
    """Split raw text (chưa phonemize) thành chunks <= max_chars."""
    if not text:
        return []

    # Protect URLs and emails from splitting (done at top level)
    text, protected_urls = _protect_urls_and_emails(text)
    
    paragraphs   = RE_NEWLINE.split(text.strip())
    final_chunks: List[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Protect abbreviations for EACH paragraph
        para, protected_abbrevs = _protect_abbreviations(para)
        
        sentences = RE_SENTENCE_END.split(para)
        buffer    = ""
        local_chunks = []  # Chunks for this paragraph

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > max_chars:
                if buffer:
                    local_chunks.append(buffer)
                    buffer = ""

                # First try splitting by minor punctuation (comma, semicolon, colon)
                sub_parts = RE_MINOR_PUNCT.split(sentence)
                
                # Also try splitting by dashes between words (not inside URLs)
                temp_parts = []
                for part in sub_parts:
                    if not RE_URL_EMAIL.search(part) and not part.startswith("__PROTECTED_"):
                        # Safe to try dash split
                        dashed = RE_MINOR_DASH.split(part)
                        temp_parts.extend(dashed)
                    else:
                        temp_parts.append(part)
                sub_parts = temp_parts
                
                for part in sub_parts:
                    part = part.strip()
                    if not part:
                        continue
                    # Skip if part is just a protected URL placeholder
                    if part.startswith("__PROTECTED_") or part.startswith("__ABBREV_"):
                        if buffer and len(buffer) + 1 + len(part) <= max_chars:
                            buffer = (buffer + ' ' + part) if buffer else part
                        elif buffer:
                            local_chunks.append(buffer)
                            buffer = part
                        continue
                    if len(buffer) + 1 + len(part) <= max_chars:
                        buffer = (buffer + ' ' + part) if buffer else part
                    else:
                        if buffer:
                            local_chunks.append(buffer)
                        buffer = part
                        if len(buffer) > max_chars:
                            words, current = buffer.split(), ""
                            for word in words:
                                if current and len(current) + 1 + len(word) > max_chars:
                                    local_chunks.append(current)
                                    current = word
                                else:
                                    current = (current + ' ' + word) if current else word
                            buffer = current
            else:
                if buffer and len(buffer) + 1 + len(sentence) > max_chars:
                    local_chunks.append(buffer)
                    buffer = sentence
                else:
                    buffer = (buffer + ' ' + sentence) if buffer else sentence

        if buffer:
            local_chunks.append(buffer)
        
        # Restore abbreviations for this paragraph's chunks
        for chunk in local_chunks:
            restored = _restore_abbreviations(chunk, protected_abbrevs)
            final_chunks.append(restored)

    # Restore URLs
    final_chunks = [_restore_urls_and_emails(c, protected_urls) for c in final_chunks]
    
    return [c.strip() for c in final_chunks if c.strip()]

# ─── v2 helpers ──────────────────────────────────────────────────────────────

def _pick_strongest(m: re.Match) -> str:
    s = m.group(0)
    return '!' if '!' in s else '?' if '?' in s else '.'


def _clean_phoneme_noise(text: str) -> str:
    for pattern, repl in _NOISE_RULES:
        text = pattern.sub(repl, text)
    return _MULTI_PUNCT.sub(_pick_strongest, text).strip()


def _find_best_split(text: str, max_size: int) -> Tuple[int, bool]:
    mid = max_size // 2
    best_comma_pos, best_comma_dist = -1, max_size
    best_space_pos, best_space_dist = -1, max_size

    for i in range(min(max_size, len(text))):
        ch = text[i]
        if ch == ',':
            d = abs(i - mid)
            if d < best_comma_dist:
                best_comma_dist, best_comma_pos = d, i
        elif ch == ' ':
            d = abs(i - mid)
            if d < best_space_dist:
                best_space_dist, best_space_pos = d, i

    if best_comma_pos != -1:
        return best_comma_pos, True
    if best_space_pos != -1:
        return best_space_pos, False
    return -1, False


def _smart_split_body(text: str, max_chunk_size: int) -> List[str]:
    result: List[str] = []
    stack = [text.strip()]

    while stack:
        seg = stack.pop()
        if not seg:
            continue
        if len(seg) <= max_chunk_size:
            result.append(seg)
            continue

        pos, _ = _find_best_split(seg, max_chunk_size)
        if pos != -1:
            left  = seg[:pos].rstrip()
            right = seg[pos + 1:].lstrip()
        else:
            cut = max_chunk_size
            while cut > 0 and seg[cut - 1] != ' ':
                cut -= 1
            if cut == 0:
                cut = max_chunk_size
            left  = seg[:cut].rstrip()
            right = seg[cut:].lstrip()

        if right:
            stack.append(right)
        if left:
            stack.append(left)

    return result


def _split_sentence(sent: str, max_chunk_size: int) -> List[PhoneChunk]:
    sent = sent.strip()
    if not sent:
        return []

    if sent[-1] in '.!?':
        body, punct = sent[:-1].rstrip(), sent[-1]
    else:
        body, punct = sent, '.'

    if not body:
        return []

    if len(sent) <= max_chunk_size:
        return [PhoneChunk(text=body + punct, is_sentence_end=True)]

    sub_chunks = _smart_split_body(body, max_chunk_size)
    if not sub_chunks:
        return [PhoneChunk(text=punct, is_sentence_end=True)]

    last_idx = len(sub_chunks) - 1
    result = []
    for i, chunk in enumerate(sub_chunks):
        if not chunk:
            continue
        # For all chunks except the last, add a period to indicate natural pause
        # This helps the TTS model understand where to pause
        if i < last_idx:
            result.append(PhoneChunk(
                text=chunk + '.',
                is_sentence_end=False,  # False because it's not a real sentence end
            ))
        else:
            result.append(PhoneChunk(
                text=chunk + punct,
                is_sentence_end=True,
            ))
    return result

# ─── v2: split phoneme string ────────────────────────────────────────────────

def split_into_chunks_v2(
    full_phones: str,
    max_chunk_size: int = 256,
    min_chunk_size: int = 10,
) -> List[PhoneChunk]:
    """
    Phân đoạn chuỗi phoneme thành các PhoneChunk.
      is_sentence_end=True  → kết thúc câu thật → cần silence
      is_sentence_end=False → cắt nhân tạo → không cần silence
    """
    if not full_phones:
        return []

    full_phones = _clean_phoneme_noise(full_phones)
    
    # Protect URLs and abbreviations before processing
    full_phones, protected_urls = _protect_urls_and_emails(full_phones)
    full_phones, protected_abbrevs = _protect_abbreviations(full_phones)

    raw_parts: List[PhoneChunk] = []
    for para in RE_NEWLINE.split(full_phones):
        para = para.strip()
        if not para:
            continue
        for sent in RE_SENTENCE_FINDALL.findall(para):
            sent = sent.strip()
            if sent:
                raw_parts.extend(_split_sentence(sent, max_chunk_size))

    if not raw_parts:
        return []
    
    # Restore protected content in chunks
    for chunk in raw_parts:
        chunk.text = _restore_urls_and_emails(_restore_abbreviations(chunk.text, protected_abbrevs), protected_urls)

    merged: List[PhoneChunk] = []
    i, n = 0, len(raw_parts)
    while i < n:
        cur = raw_parts[i]
        while len(cur.text) < min_chunk_size and i + 1 < n:
            nxt       = raw_parts[i + 1]
            candidate = cur.text.rstrip('.!?').rstrip() + ' ' + nxt.text
            if len(candidate) <= max_chunk_size:
                cur = PhoneChunk(text=candidate, is_sentence_end=nxt.is_sentence_end)
                i += 1
            else:
                break
        merged.append(cur)
        i += 1

    if len(merged) >= 2 and len(merged[-1].text) < min_chunk_size:
        last      = merged.pop()
        candidate = merged[-1].text.rstrip('.!?').rstrip() + ' ' + last.text
        if len(candidate) <= max_chunk_size:
            merged[-1] = PhoneChunk(text=candidate, is_sentence_end=last.is_sentence_end)
        else:
            merged.append(last)

    return merged


def get_silence_duration_v2(chunk: PhoneChunk) -> float:
    """
    Silence sau chunk (giây).
      is_sentence_end=False → 0.0s
      kết thúc '!'/'?' → 0.4s
      kết thúc '.' → 0.3s
    """
    if not chunk.is_sentence_end:
        return 0.0
    return 0.4 if chunk.text.strip()[-1] in '!?' else 0.3

# ─── Misc ────────────────────────────────────────────────────────────────────

def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'y', 'on')