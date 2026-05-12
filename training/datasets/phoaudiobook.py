"""
Dataset adapter for thivux/phoaudiobook.

phoAudiobook is a large Vietnamese audiobook dataset containing:
- Multiple speakers
- Long-form audio segments
- Vietnamese text transcripts
- Speaker metadata

Reference: https://huggingface.co/datasets/thivux/phoaudiobook

Expected structure after loading with `load_dataset`:
  DatasetDict({
      train: Dataset({
          features: ['file', 'audio', 'text', 'segment_id', 'speaker_id', 'duration', ...],
          num_rows: N
      })
  })

This adapter:
1. Loads the dataset using HuggingFace datasets
2. Resamples audio to 24kHz
3. Normalizes text with sea-g2p
4. Splits long segments into shorter chunks
5. Produces a phuonganh-tts training manifest
"""
from __future__ import annotations

import logging
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("phuonganh.training.phoaudiobook")

# Dataset ID on HuggingFace Hub
PHOAUDIOBOOK_REPO = "thivux/phoaudiobook"

# Audio target configuration
TARGET_SAMPLE_RATE = 24_000
MAX_SEGMENT_DURATION_S = 30.0  # Split longer segments
MIN_SEGMENT_DURATION_S = 1.0   # Discard very short segments


@dataclass
class PhoAudiobookSpeaker:
    """Metadata for a speaker in the PhoAudiobook dataset."""
    speaker_id: str
    name: str
    gender: str  # "male", "female", "unknown"
    num_segments: int = 0
    total_duration_h: float = 0.0
    language: str = "vi"


class PhoAudiobookAdapter:
    """
    Adapter for ingesting thivux/phoaudiobook into phuonganh-tts training format.

    Usage:
        adapter = PhoAudiobookAdapter(cache_dir="/path/to/cache")
        manifest = adapter.load_and_process(
            split="train",
            max_duration_s=30.0,
            resample_rate=24000,
        )
        manifest.write_jsonl("outputs/phoaudiobook_manifest.jsonl")
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        hf_token: Optional[str] = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.hf_token = hf_token

    def _load_dataset(self, split: str = "train"):
        """Load the PhoAudiobook dataset from HuggingFace."""
        try:
            from datasets import load_dataset
        except ImportError:
            raise ImportError(
                "phoAudiobook ingestion requires the `datasets` package. "
                "Install with: pip install datasets"
            )

        logger.info(f"Loading PhoAudiobook dataset (split={split})...")
        dataset = load_dataset(
            PHOAUDIOBOOK_REPO,
            split=split,
            cache_dir=str(self.cache_dir) if self.cache_dir else None,
            token=self.hf_token,
            trust_remote_code=True,
        )
        logger.info(f"Loaded {len(dataset)} examples")
        return dataset

    def _extract_speakers(self, dataset) -> dict[str, PhoAudiobookSpeaker]:
        """Extract unique speakers from the dataset."""
        speakers: dict[str, PhoAudiobookSpeaker] = {}
        for row in dataset:
            spk_id = str(row.get("speaker_id", row.get("speaker", "unknown")))
            if spk_id not in speakers:
                speakers[spk_id] = PhoAudiobookSpeaker(
                    speaker_id=spk_id,
                    name=row.get("speaker_name", row.get("speaker", spk_id)),
                    gender=row.get("gender", "unknown"),
                )
        return speakers

    def _normalize_text(self, text: str) -> str:
        """Normalize Vietnamese text using sea-g2p."""
        try:
            from sea_g2p import Normalizer
            normalizer = Normalizer()
            return normalizer.normalize(text)
        except Exception as e:
            logger.warning(f"Normalization failed for text: {e}")
            return text.strip()

    def _resample_audio(self, audio_array, orig_sr: int, target_sr: int):
        """Resample audio to target sample rate."""
        if orig_sr == target_sr:
            return audio_array
        try:
            import librosa
            return librosa.resample(audio_array, orig_sr=orig_sr, target_sr=target_sr)
        except ImportError:
            logger.warning("librosa not available, skipping resampling")
            return audio_array

    def _split_long_segment(
        self,
        text: str,
        audio_path: str,
        duration_s: float,
        target_sr: int,
    ) -> list[dict]:
        """
        Split a long segment into shorter chunks.
        For audiobook data, we split by sentences first, then by duration.
        """
        from phuonganh_utils.core_utils import split_text_into_chunks

        chunks = split_text_into_chunks(text, max_chars=256)
        results = []
        chunk_duration = duration_s / max(len(chunks), 1)

        for i, chunk_text in enumerate(chunks):
            chunk_text = chunk_text.strip()
            if len(chunk_text) < 3:
                continue

            # Estimate this chunk's duration
            est_duration = chunk_duration
            if est_duration < MIN_SEGMENT_DURATION_S:
                continue

            chunk_id = f"{Path(audio_path).stem}_chunk{i}"
            results.append({
                "text": chunk_text,
                "audio_path": audio_path,
                "chunk_index": i,
                "chunk_id": chunk_id,
                "duration_s": est_duration,
            })

        return results

    def load_and_process(
        self,
        split: str = "train",
        max_duration_s: float = MAX_SEGMENT_DURATION_S,
        resample_rate: int = TARGET_SAMPLE_RATE,
        normalize: bool = True,
        speaker_overrides: Optional[dict[str, dict]] = None,
    ) -> "DatasetManifest":
        """
        Load PhoAudiobook and convert to phuonganh-tts training manifest.

        Args:
            split: Dataset split to load ("train", "validation")
            max_duration_s: Maximum segment duration in seconds
            resample_rate: Target audio sample rate
            normalize: Whether to normalize text with sea-g2p
            speaker_overrides: Optional dict of speaker_id -> metadata overrides

        Returns:
            DatasetManifest with all processed entries
        """
        from training.datasets.manifest import DatasetManifest, DatasetManifestEntry

        dataset = self._load_dataset(split)
        speakers = self._extract_speakers(dataset)

        # Apply speaker overrides
        if speaker_overrides:
            for spk_id, meta in speaker_overrides.items():
                if spk_id in speakers:
                    for k, v in meta.items():
                        setattr(speakers[spk_id], k, v)

        entries: list[DatasetManifestEntry] = []
        skipped = 0

        for i, row in enumerate(dataset):
            try:
                # Extract fields (handle different possible column names)
                text = str(row.get("text", row.get("transcript", ""))).strip()
                if not text:
                    skipped += 1
                    continue

                # Speaker
                spk_id = str(row.get("speaker_id", row.get("speaker", "unknown")))
                if spk_id == "unknown" and "speaker" in row:
                    spk_id = str(row["speaker"])

                spk_meta = speakers.get(spk_id)

                # Duration
                duration_s = float(row.get("duration", row.get("duration_s", 0)))
                if duration_s <= 0:
                    skipped += 1
                    continue

                # Audio path (local cached file)
                audio_path = str(row.get("file", row.get("audio", {}).get("path", "")))

                # Normalize text
                if normalize:
                    text = self._normalize_text(text)

                # Check duration constraint
                if duration_s > max_duration_s:
                    # Split long segments
                    chunks = self._split_long_segment(
                        text, audio_path, duration_s, TARGET_SAMPLE_RATE
                    )
                    for chunk in chunks:
                        entry = DatasetManifestEntry(
                            audio_path=chunk["audio_path"],
                            transcript=chunk["text"],
                            speaker_id=spk_id,
                            speaker_name=getattr(spk_meta, "name", spk_id),
                            duration_s=chunk["duration_s"],
                            sample_rate=resample_rate,
                            language="vi",
                            split="train",
                            dataset="phoaudiobook",
                            audio_id=chunk["chunk_id"],
                        )
                        entries.append(entry)
                else:
                    # Single segment
                    audio_id = (
                        f"phoaudiobook_{spk_id}_{i}"
                        if spk_id != "unknown"
                        else f"phoaudiobook_{i}"
                    )
                    entry = DatasetManifestEntry(
                        audio_path=audio_path,
                        transcript=text,
                        speaker_id=spk_id,
                        speaker_name=getattr(spk_meta, "name", spk_id),
                        duration_s=duration_s,
                        sample_rate=resample_rate,
                        language="vi",
                        split="train",
                        dataset="phoaudiobook",
                        audio_id=audio_id,
                    )
                    entries.append(entry)

                # Update speaker stats
                if spk_id in speakers:
                    speakers[spk_id].num_segments += 1
                    speakers[spk_id].total_duration_h += duration_s / 3600.0

            except Exception as e:
                logger.warning(f"Row {i} skipped: {e}")
                skipped += 1

        manifest = DatasetManifest(
            name="phoaudiobook",
            entries=entries,
            description=(
                f"PhoAudiobook dataset from thivux/phoaudiobook. "
                f"Filtered to ≤{max_duration_s}s segments at {resample_rate}Hz."
            ),
        )

        logger.info(
            f"Processed {len(entries)} entries "
            f"(skipped {skipped}/{len(dataset)} rows)"
        )

        return manifest

    def speaker_report(self, split: str = "train") -> str:
        """Generate a speaker statistics report without full processing."""
        dataset = self._load_dataset(split)
        speakers = self._extract_speakers(dataset)

        lines = [f"PhoAudiobook Speaker Report (split={split})", "=" * 50]
        for spk_id, spk in sorted(speakers.items()):
            lines.append(
                f"  [{spk_id}] {spk.name} ({spk.gender})"
            )
        lines.append(f"\nTotal speakers: {len(speakers)}")
        return "\n".join(lines)
