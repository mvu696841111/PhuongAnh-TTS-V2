

def PhuongAnh(mode="standard", **kwargs):
    """
    Factory function for phuonganh-tts.

    Args:
        mode: 'standard' (CPU/GPU-GGUF), 'fast' (GPU-LMDeploy), 'remote' (API), 'xpu' (Intel GPU)
        **kwargs: Arguments for chosen class

    Returns:
        BasePhuongAnhTTS: An instance of a phuonganh-tts implementation.
    """
    match mode:
        case "remote" | "api":
            from .remote import RemotePhuongAnhTTS
            return RemotePhuongAnhTTS(**kwargs)
        case "fast" | "gpu":
            from .fast import FastPhuongAnhTTS
            return FastPhuongAnhTTS(**kwargs)
        case "turbo":
            from .turbo import TurboPhuongAnhTTS
            return TurboPhuongAnhTTS(**kwargs)
        case "turbo_gpu":
            from .turbo import TurboGPUPhuongAnhTTS
            return TurboGPUPhuongAnhTTS(**kwargs)
        case "xpu":
            try:
                from .core_xpu import XPUPhuongAnhTTS
                return XPUPhuongAnhTTS(**kwargs)
            except Exception as e:
                raise RuntimeError(f"Failed to load XPU backend. Ensure Intel GPU drivers and torch.xpu are installed: {e}") from e
        case "standard":
            from .standard import PhuongAnhTTS
            return PhuongAnhTTS(**kwargs)
