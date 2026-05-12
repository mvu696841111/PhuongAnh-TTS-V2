# phuonganh-tts Training Infrastructure

Vietnamese TTS fine-tuning and training support for phuonganh-tts.

## Directory Structure

```
training/
├── datasets/           — Dataset adapters and manifest schema
│   ├── __init__.py
│   ├── manifest.py     — JSONL training manifest format
│   └── phoaudiobook.py — thivux/phoaudiobook adapter
├── preprocessing/     — Audio and text preprocessing
│   └── audio.py        — Resampling, normalization, phoneme extraction
└── configs/            — Training configurations
    └── training_config.py  — LoRA hyperparameters
```

## Quick Start

### 1. Ingest PhoAudiobook Dataset

```python
from training.datasets.phoaudiobook import PhoAudiobookAdapter

adapter = PhoAudiobookAdapter(
    cache_dir="/path/to/hf_cache",
    hf_token="hf_..."  # optional
)

# Load and process
manifest = adapter.load_and_process(
    split="train",
    max_duration_s=30.0,
    resample_rate=24000,
    normalize=True,
)

# Save manifest
manifest.write_jsonl("training/outputs/phoaudiobook_manifest.jsonl")

# Speaker report
print(adapter.speaker_report())
```

### 2. Preprocess Audio Files

```python
from training.preprocessing.audio import AudioPreprocessor, PhonemeExtractor

# Preprocess audio directory
proc = AudioPreprocessor()
results = proc.batch_process(
    input_dir="path/to/audio/files",
    output_dir="path/to/output",
)

# Extract phonemes
extractor = PhonemeExtractor()
phonemes = extractor.extract("Xin chào các bạn")
print(phonemes)
```

### 3. Fine-tune with LoRA

```bash
# Using the existing finetune script
python finetune/train.py \
    --base_model Nemmer/phuonganh-tts-v2 \
    --dataset training/outputs/manifest.jsonl \
    --output_dir finetune/output \
    --num_epochs 3 \
    --batch_size 2 \
    --learning_rate 1e-4

# Merge LoRA into base model
python finetune/merge_lora.py \
    --base_model Nemmer/phuonganh-tts-v2 \
    --lora_path finetune/output/final \
    --output finetune/output/merged_model
```

## Training Manifest Format

Each line in a manifest JSONL file is a JSON object:

```json
{
  "audio_path": "/path/to/audio.wav",
  "transcript": "Xin chào các bạn",
  "phonemes": "sɪn tɕaʊ kac6 bɐjN4",
  "speaker_id": "speaker_001",
  "speaker_name": "Người đọc 1",
  "duration_s": 2.5,
  "sample_rate": 24000,
  "language": "vi",
  "split": "train",
  "dataset": "my_dataset",
  "audio_id": "sample_001"
}
```

Required fields: `audio_path`, `transcript`, `duration_s`, `sample_rate`
Optional fields: `phonemes`, `speaker_id`, `speaker_name`, `language`, `split`, `dataset`

## PhoAudiobook Dataset

Source: [thivux/phoaudiobook](https://huggingface.co/datasets/thivux/phoaudiobook)

The adapter:
1. Loads the dataset from HuggingFace Hub
2. Resamples audio to 24kHz
3. Normalizes Vietnamese text with sea-g2p
4. Splits long segments into ≤30s chunks
5. Generates a standard training manifest

## Preprocessing Configuration

| Parameter | Default | Description |
|---|---|---|
| `target_sr` | 24000 | Target sample rate |
| `trim_silence` | True | Remove leading/trailing silence |
| `silence_threshold_db` | -40.0 | Silence detection threshold (dB) |
| `min_segment_duration_s` | 1.0 | Discard shorter segments |
| `max_segment_duration_s` | 30.0 | Split longer segments |
| `normalize_volume` | True | Normalize to -20 dBFS |

## LoRA Fine-tuning

LoRA (Low-Rank Adaptation) enables efficient fine-tuning of large models
with minimal parameter updates.

### Default LoRA Config

| Parameter | Value | Description |
|---|---|---|
| `r` | 16 | LoRA rank |
| `alpha` | 32 | Scaling factor |
| `dropout` | 0.05 | Dropout probability |
| `target_modules` | q,v,k,o_proj + MLP | Which layers to adapt |
| `learning_rate` | 1e-4 | Fine-tuning LR |
| `batch_size` | 2 per device | Effective BS = 8 with gradient accum |

### Requirements for Fine-tuning

- GPU with ≥16GB VRAM (24GB recommended)
- HuggingFace transformers
- PEFT (Parameter-Efficient Fine-Tuning)
- phuonganh-tts base model
- Training manifest in JSONL format

## Compatibility

This training infrastructure is designed to work with `phuonganh_tts`, exposing the `PhuongAnh` factory interface.
