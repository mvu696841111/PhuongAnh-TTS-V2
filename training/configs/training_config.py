"""
Training configuration for phuonganh-tts (LoRA fine-tuning).

This config is used by training/datasets/train.py.
Default values target fine-tuning phuonganh-tts-v2 on a single GPU (24GB VRAM).
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LoRAConfig:
    """LoRA (Low-Rank Adaptation) configuration."""
    r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list = field(default_factory=lambda: [
        "q_proj", "v_proj", "k_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ])
    bias: str = "none"
    task_type: str = "CAUSAL_LM"


@dataclass
class TrainingConfig:
    """Full training configuration."""
    # Model
    base_model: str = "./models/phuonganh-tts-v2"
    model_revision: Optional[str] = None

    # LoRA
    lora: LoRAConfig = field(default_factory=LoRAConfig)

    # Data
    dataset_path: str = "training/outputs/manifest.jsonl"
    dataset_name: str = "custom"
    max_seq_length: int = 512
    overwrite_cache: bool = True

    # Training
    output_dir: str = "finetune/output"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 2
    per_device_eval_batch_size: int = 2
    gradient_accumulation_steps: int = 4
    learning_rate: float = 1e-4
    weight_decay: float = 0.01
    warmup_ratio: float = 0.03
    lr_scheduler_type: str = "cosine"
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 500
    save_total_limit: int = 3

    # Precision
    bf16: bool = True
    fp16: bool = False

    # Optimization
    optim: str = "paged_adamw_8bit"
    max_grad_norm: float = 1.0
    group_by_length: bool = False

    # Misc
    seed: int = 42
    report_to: str = "none"
    hub_token: Optional[str] = None

    def effective_batch_size(self) -> int:
        return self.per_device_train_batch_size * self.gradient_accumulation_steps


# Default config instance
default_training_config = TrainingConfig()
default_lora_config = LoRAConfig()
