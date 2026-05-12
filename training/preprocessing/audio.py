"""
Audio preprocessing pipeline for phuonganh-tts training data.

Handles:
- Audio loading and resampling to 24kHz
- Silence trimming
- Volume normalization
- Phoneme extraction
- Manifest generation
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("phuonganh.training.preprocessing")


@dataclass
class PreprocessingConfig:
    """Configuration for the audio preprocessing pipeline."""
    target_sr: int = 24_000
    trim_silence: bool = True
    silence_threshold_db: float = -40.0
    min_segment_duration_s: float = 1.0
    max_segment_duration_s: float = 30.0
    normalize_volume: bool = True
    target_loudness_db: float = -20.0
    remove_dc_offset: bool = True
    lowcut_freq_hz: float = 80.0


class AudioPreprocessor:
    """
    Preprocess audio files for training.

    This class provides utilities to:
    - Load audio from various formats (WAV, FLAC, MP3, etc.)
    - Resample to target sample rate
    - Trim silence from beginning/end
    - Normalize volume
    - Validate audio quality
    """

    def __init__(self, config: Optional[PreprocessingConfig] = None):
        self.config = config or PreprocessingConfig()

    def preprocess_file(
        self,
        audio_path: str | Path,
        output_path: Optional[str | Path] = None,
    ) -> dict:
        """
        Preprocess a single audio file.

        Args:
            audio_path: Path to input audio file
            output_path: Optional output path (default: overwrite in place)

        Returns:
            dict with keys: duration_s, sample_rate, loudness_db, path
        """
        import soundfile as sf
        import librosa
        import numpy as np

        audio_path = Path(audio_path)
        output_path = Path(output_path) if output_path else audio_path

        # Load audio
        audio, sr = sf.read(str(audio_path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # Convert stereo to mono

        original_sr = sr
        original_duration = len(audio) / sr

        # Resample
        if sr != self.config.target_sr:
            audio = librosa.resample(
                audio, orig_sr=sr, target_sr=self.config.target_sr
            )
            sr = self.config.target_sr

        # Remove DC offset
        if self.config.remove_dc_offset:
            audio = audio - np.mean(audio)

        # Lowcut filter
        if self.config.lowcut_freq_hz > 0 and self.config.lowcut_freq > 0:
            audio = self._lowcut(audio, sr, self.config.lowcut_freq_hz)

        # Trim silence
        if self.config.trim_silence:
            audio, _ = librosa.effects.trim(
                audio,
                top_db=abs(self.config.silence_threshold_db),
            )

        # Normalize volume
        if self.config.normalize_volume:
            audio = self._normalize_loudness(audio, self.config.target_loudness_db)

        # Check duration
        duration = len(audio) / sr
        if duration < self.config.min_segment_duration_s:
            logger.warning(
                f"File {audio_path} too short after preprocessing: "
                f"{duration:.2f}s < {self.config.min_segment_duration_s}s"
            )
            return {
                "path": str(audio_path),
                "duration_s": 0,
                "sample_rate": sr,
                "loudness_db": None,
                "skipped": True,
                "skip_reason": "too_short",
            }

        # Save output
        sf.write(str(output_path), audio, sr)
        loudness = self._estimate_loudness(audio)

        logger.info(
            f"Preprocessed: {audio_path.name} "
            f"({original_duration:.1f}s → {duration:.1f}s, {loudness:.1f} dBFS)"
        )

        return {
            "path": str(output_path),
            "duration_s": duration,
            "sample_rate": sr,
            "loudness_db": loudness,
            "original_sr": original_sr,
            "skipped": False,
        }

    def _lowcut(self, audio, sr: int, cutoff_hz: float) -> np.ndarray:
        """Apply a simple low-cut filter."""
        try:
            import scipy.signal as signal
            nyq = sr / 2
            b, a = signal.butter(2, cutoff_hz / nyq, btype="high")
            return signal.filtfilt(b, a, audio)
        except Exception:
            return audio

    def _normalize_loudness(self, audio, target_db: float) -> np.ndarray:
        """Normalize audio to target loudness in dBFS."""
        import numpy as np
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-8:
            return audio
        current_db = 20 * np.log10(rms)
        gain_db = target_db - current_db
        gain = 10 ** (gain_db / 20)
        return np.clip(audio * gain, -1.0, 1.0)

    def _estimate_loudness(self, audio) -> float:
        """Estimate loudness in dBFS."""
        import numpy as np
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-8:
            return -96.0
        return 20 * np.log10(rms)

    def batch_process(
        self,
        input_dir: str | Path,
        output_dir: Optional[str | Path] = None,
        extensions: tuple = (".wav", ".flac", ".mp3"),
    ) -> list[dict]:
        """
        Preprocess all audio files in a directory.

        Args:
            input_dir: Directory containing audio files
            output_dir: Optional output directory (default: same as input)
            extensions: File extensions to process

        Returns:
            List of results dicts (one per file)
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir) if output_dir else input_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for audio_file in sorted(input_dir.rglob("*")):
            if audio_file.suffix.lower() not in extensions:
                continue

            rel_path = audio_file.relative_to(input_dir)
            out_path = output_dir / rel_path

            out_path.parent.mkdir(parents=True, exist_ok=True)
            result = self.preprocess_file(audio_file, out_path)
            result["input_path"] = str(audio_file)
            results.append(result)

        return results


class PhonemeExtractor:
    """
    Extract phoneme sequences from text using sea-g2p.
    Used to pre-compute phonemes for faster training.
    """

    def __init__(self):
        self._normalizer = None
        self._g2p = None

    def _ensure_initialized(self):
        if self._normalizer is None:
            from sea_g2p import Normalizer, G2P
            self._normalizer = Normalizer()
            self._g2p = G2P()

    def extract(self, text: str, normalize: bool = True) -> str:
        """
        Extract phoneme sequence from text.

        Args:
            text: Input Vietnamese text
            normalize: Whether to normalize text first

        Returns:
            Space-separated phoneme sequence
        """
        self._ensure_initialized()

        if normalize:
            text = self._normalizer.normalize(text)

        phonemes = self._g2p(text)
        return phonemes

    def extract_batch(self, texts: list[str]) -> list[str]:
        """Extract phonemes for a batch of texts."""
        return [self.extract(t) for t in texts]


def compute_dataset_stats(manifest_path: str | Path) -> dict:
    """
    Compute statistics for a dataset manifest.

    Returns:
        dict with keys: total_duration_h, num_samples, avg_duration_s,
                       speaker_counts, language_counts
    """
    from training.datasets.manifest import load_manifest
    import numpy as np

    manifest = load_manifest(manifest_path)

    durations = [e.duration_s for e in manifest.entries]

    return {
        "dataset": manifest.name,
        "total_entries": len(manifest.entries),
        "total_duration_h": sum(durations) / 3600,
        "avg_duration_s": np.mean(durations) if durations else 0,
        "median_duration_s": np.median(durations) if durations else 0,
        "min_duration_s": min(durations) if durations else 0,
        "max_duration_s": max(durations) if durations else 0,
        "num_speakers": len(manifest.speaker_ids()),
        "speaker_ids": manifest.speaker_ids(),
        "splits": {
            "train": len(manifest.train_entries),
            "val": len(manifest.val_entries),
            "test": len(manifest.test_entries),
        },
    }
