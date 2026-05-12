"""
Dataset manifest schema and validation for phuonganh-tts training.

A manifest is a JSONL file where each line is a JSON object representing one
training sample. This is the canonical format expected by the training pipeline.

Schema (per line):
{
    "audio_path": str,          # Absolute path to audio file (WAV/FLAC)
    "transcript": str,          # Normalized text transcript
    "phonemes": str,            # (Optional) pre-computed phoneme sequence
    "speaker_id": str,          # Speaker identifier (for multi-speaker)
    "speaker_name": str,        # (Optional) human-readable speaker name
    "duration_s": float,        # Audio duration in seconds
    "sample_rate": int,         # Audio sample rate (should be 24000)
    "language": str,            # Language code ("vi", "en", "mixed")
    "split": str,              # Dataset split ("train", "val", "test")
    "dataset": str,             # Source dataset name
    "audio_id": str,           # Unique identifier for this sample
}
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger("phuonganh.training.datasets")


@dataclass
class DatasetManifestEntry:
    """A single entry in a training manifest."""
    audio_path: str
    transcript: str
    speaker_id: str = "default"
    speaker_name: str = ""
    duration_s: float = 0.0
    sample_rate: int = 24000
    language: str = "vi"
    split: str = "train"
    dataset: str = "unknown"
    audio_id: str = ""
    phonemes: str = ""

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors = []
        if not self.audio_path:
            errors.append("audio_path is required")
        if not self.transcript:
            errors.append("transcript is required")
        if self.duration_s <= 0:
            errors.append(f"duration_s must be positive, got {self.duration_s}")
        if self.sample_rate not in (16000, 22050, 24000, 44100, 48000):
            errors.append(f"sample_rate {self.sample_rate} is unusual")
        if self.language not in ("vi", "en", "mixed"):
            errors.append(f"language '{self.language}' not recognized")
        if self.split not in ("train", "val", "test"):
            errors.append(f"split '{self.split}' not recognized")
        return errors

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove empty fields for compactness
        return {k: v for k, v in d.items() if v != "" and v != 0.0}

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetManifestEntry":
        return cls(
            audio_path=d.get("audio_path", ""),
            transcript=d.get("transcript", ""),
            speaker_id=d.get("speaker_id", "default"),
            speaker_name=d.get("speaker_name", ""),
            duration_s=float(d.get("duration_s", 0)),
            sample_rate=int(d.get("sample_rate", 24000)),
            language=d.get("language", "vi"),
            split=d.get("split", "train"),
            dataset=d.get("dataset", "unknown"),
            audio_id=d.get("audio_id", ""),
            phonemes=d.get("phonemes", ""),
        )


@dataclass
class DatasetManifest:
    """A collection of manifest entries with metadata."""
    name: str
    entries: list[DatasetManifestEntry] = field(default_factory=list)
    version: str = "1.0"
    description: str = ""
    total_duration_h: float = 0.0
    num_speakers: int = 0

    def __post_init__(self):
        if self.entries:
            self._compute_stats()

    def _compute_stats(self) -> None:
        self.total_duration_h = sum(e.duration_s for e in self.entries) / 3600.0
        self.num_speakers = len(set(e.speaker_id for e in self.entries))

    @property
    def num_entries(self) -> int:
        return len(self.entries)

    @property
    def train_entries(self) -> list[DatasetManifestEntry]:
        return [e for e in self.entries if e.split == "train"]

    @property
    def val_entries(self) -> list[DatasetManifestEntry]:
        return [e for e in self.entries if e.split == "val"]

    @property
    def test_entries(self) -> list[DatasetManifestEntry]:
        return [e for e in self.entries if e.split == "test"]

    def speaker_ids(self) -> list[str]:
        return sorted(set(e.speaker_id for e in self.entries))

    def summary(self) -> str:
        return (
            f"Dataset: {self.name}\n"
            f"  Entries: {self.num_entries}\n"
            f"  Duration: {self.total_duration_h:.1f}h\n"
            f"  Speakers: {self.num_speakers}\n"
            f"  Train: {len(self.train_entries)} | Val: {len(self.val_entries)} | Test: {len(self.test_entries)}\n"
        )

    def write_jsonl(self, path: Path | str) -> None:
        """Write manifest to JSONL file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for entry in self.entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Written {self.num_entries} entries to {path}")

    @classmethod
    def read_jsonl(cls, path: Path | str) -> "DatasetManifest":
        """Read manifest from JSONL file."""
        path = Path(path)
        entries = []
        errors = []

        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    entry = DatasetManifestEntry.from_dict(d)
                    entry.audio_id = entry.audio_id or f"{path.stem}_{i}"
                    errs = entry.validate()
                    if errs:
                        errors.append(f"Line {i}: {', '.join(errs)}")
                    else:
                        entries.append(entry)
                except json.JSONDecodeError as e:
                    errors.append(f"Line {i}: JSON error — {e}")

        if errors:
            for err in errors[:10]:
                logger.warning(err)
            if len(errors) > 10:
                logger.warning(f"... and {len(errors) - 10} more errors")

        manifest = cls(
            name=path.stem,
            entries=entries,
        )
        logger.info(f"Loaded {len(entries)} entries from {path}")
        return manifest


def load_manifest(path: Path | str) -> DatasetManifest:
    """Load a manifest from a JSONL file."""
    return DatasetManifest.read_jsonl(path)
