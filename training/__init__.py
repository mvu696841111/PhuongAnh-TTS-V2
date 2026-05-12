"""
Training package for phuonganh-tts.

Directory structure:
  training/
    datasets/        — Dataset adapters and manifest schema
      manifest.py     — JSONL manifest format
      phoaudiobook.py — PhoAudiobook dataset adapter
    preprocessing/   — Audio/text preprocessing
      audio.py       — Resampling, normalization, phoneme extraction
    configs/         — Training configs
      training_config.py — LoRA and training hyperparameters
    README.md        — This file

Usage:
  # 1. Ingest PhoAudiobook dataset
  python -c "
  from training.datasets.phoaudiobook import PhoAudiobookAdapter
  adapter = PhoAudiobookAdapter()
  manifest = adapter.load_and_process(split='train', max_duration_s=30.0)
  manifest.write_jsonl('training/outputs/phoaudiobook_manifest.jsonl')
  "

  # 2. Preprocess audio
  python -c "
  from training.preprocessing.audio import AudioPreprocessor, PhonemeExtractor
  proc = AudioPreprocessor()
  proc.batch_process('path/to/audio/files')
  "

  # 3. Fine-tune with LoRA
  python finetune/train.py --config training/configs/training_config.py
"""
