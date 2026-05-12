# phuonganh-tts Testing Directory

This directory contains test suites and utilities for verifying the phuonganh-tts package.

## How to run tests

Ensure you are in the project root:

```bash
uv run pytest
```

This will automatically discover and run all test suites in the `tests/` directory.

---

### Individual Test Suites
- **[test_engine_standard.py](test_engine_standard.py)**: Tests for the standard PhuongAnhTTS engine (Torch/GGUF).
- **[test_engine_remote.py](test_engine_remote.py)**: Tests for the Remote API engine.
- **[test_engine_fast.py](test_engine_fast.py)**: Tests for the Fast (LMDeploy) engine.
- **[test_factory.py](test_factory.py)**: Tests for the PhuongAnh factory class.
- **[test_utils.py](test_utils.py)**: Tests for audio and text processing utilities.

---

### Other Utilities
- **[benchmark.py](benchmark.py)**: RTF and latency benchmarking.
