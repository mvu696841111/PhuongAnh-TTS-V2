"""
Core configuration module for PhuongAnh-TTS Backend.
Loads settings from environment variables with Pydantic.
"""

from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ===========================================
    # Database
    # ===========================================
    MONGODB_URI: str = Field(
        default="mongodb://admin:phuonganh_secure_password_2024@localhost:27017/?authSource=admin",
        description="MongoDB connection URI"
    )
    MONGODB_DB_NAME: str = Field(default="phuonganh_tts", description="Database name")

    # ===========================================
    # Redis
    # ===========================================
    REDIS_URL: str = Field(default="redis://localhost:6379", description="Redis connection URL")

    # ===========================================
    # JWT & Security
    # ===========================================
    JWT_SECRET_KEY: str = Field(
        default="change-this-super-secret-key-in-production",
        description="JWT secret key for token signing"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, description="Access token expiration in minutes"
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="Refresh token expiration in days"
    )
    PASSWORD_MIN_LENGTH: int = Field(default=8, description="Minimum password length")
    BCRYPT_ROUNDS: int = Field(default=12, description="Bcrypt hashing rounds")

    # ===========================================
    # Storage
    # ===========================================
    AUDIO_STORAGE_PATH: str = Field(
        default="./data/audios", description="Path for storing audio files"
    )
    TEMP_STORAGE_PATH: str = Field(
        default="./data/temp", description="Path for temporary files"
    )
    MAX_AUDIO_SIZE_MB: int = Field(default=100, description="Maximum audio file size in MB")
    MAX_AUDIO_DURATION_SECONDS: int = Field(
        default=600, description="Maximum audio duration in seconds"
    )

    # ===========================================
    # Rate Limiting
    # ===========================================
    RATE_LIMIT_PER_MINUTE: int = Field(default=60, description="API rate limit per minute")
    RATE_LIMIT_PER_HOUR: int = Field(default=1000, description="API rate limit per hour")

    # ===========================================
    # Subscription Tier Limits
    # ===========================================
    # Free Tier
    FREE_DAILY_AUDIO_LIMIT: int = Field(default=10, description="Free tier daily audio limit")
    FREE_MONTHLY_CHARS_LIMIT: int = Field(
        default=10000, description="Free tier monthly character limit"
    )
    FREE_MAX_TEXT_LENGTH: int = Field(default=500, description="Free tier max text length")
    FREE_MAX_DURATION: int = Field(default=30, description="Free tier max audio duration")

    # Plus Tier
    PLUS_DAILY_AUDIO_LIMIT: int = Field(default=100, description="Plus tier daily audio limit")
    PLUS_MONTHLY_CHARS_LIMIT: int = Field(
        default=100000, description="Plus tier monthly character limit"
    )
    PLUS_MAX_TEXT_LENGTH: int = Field(default=2000, description="Plus tier max text length")
    PLUS_MAX_DURATION: int = Field(default=120, description="Plus tier max audio duration")

    # Pro Tier
    PRO_DAILY_AUDIO_LIMIT: int = Field(
        default=-1, description="Pro tier daily audio limit (-1 = unlimited)"
    )
    PRO_MONTHLY_CHARS_LIMIT: int = Field(
        default=500000, description="Pro tier monthly character limit"
    )
    PRO_MAX_TEXT_LENGTH: int = Field(default=10000, description="Pro tier max text length")
    PRO_MAX_DURATION: int = Field(default=600, description="Pro tier max audio duration")

    # ===========================================
    # Server
    # ===========================================
    HOST: str = Field(default="0.0.0.0", description="Server host")
    PORT: int = Field(default=8000, description="Server port")
    WORKERS: int = Field(default=4, description="Number of workers")
    RELOAD: bool = Field(default=False, description="Auto-reload on code changes")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # ===========================================
    # CORS
    # ===========================================
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:7860",
        description="Comma-separated CORS origins"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # ===========================================
    # Environment
    # ===========================================
    ENVIRONMENT: str = Field(default="development", description="Environment name")
    DEBUG: bool = Field(default=True, description="Debug mode")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


class SubscriptionLimits:
    """
    Subscription tier limits helper class.
    Provides easy access to limits based on subscription plan.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_daily_audio_limit(self, plan: str) -> int:
        """Get daily audio limit for a plan."""
        limits = {
            "free": self.settings.FREE_DAILY_AUDIO_LIMIT,
            "plus": self.settings.PLUS_DAILY_AUDIO_LIMIT,
            "pro": self.settings.PRO_DAILY_AUDIO_LIMIT,
        }
        return limits.get(plan.lower(), self.settings.FREE_DAILY_AUDIO_LIMIT)

    def get_monthly_chars_limit(self, plan: str) -> int:
        """Get monthly character limit for a plan."""
        limits = {
            "free": self.settings.FREE_MONTHLY_CHARS_LIMIT,
            "plus": self.settings.PLUS_MONTHLY_CHARS_LIMIT,
            "pro": self.settings.PRO_MONTHLY_CHARS_LIMIT,
        }
        return limits.get(plan.lower(), self.settings.FREE_MONTHLY_CHARS_LIMIT)

    def get_max_text_length(self, plan: str) -> int:
        """Get max text length for a plan."""
        limits = {
            "free": self.settings.FREE_MAX_TEXT_LENGTH,
            "plus": self.settings.PLUS_MAX_TEXT_LENGTH,
            "pro": self.settings.PRO_MAX_TEXT_LENGTH,
        }
        return limits.get(plan.lower(), self.settings.FREE_MAX_TEXT_LENGTH)

    def get_max_duration(self, plan: str) -> int:
        """Get max audio duration for a plan."""
        limits = {
            "free": self.settings.FREE_MAX_DURATION,
            "plus": self.settings.PLUS_MAX_DURATION,
            "pro": self.settings.PRO_MAX_DURATION,
        }
        return limits.get(plan.lower(), self.settings.FREE_MAX_DURATION)

    def has_watermark(self, plan: str) -> bool:
        """Check if plan requires watermark."""
        return plan.lower() == "free"

    def can_use_voice_cloning(self, plan: str) -> bool:
        """Check if plan allows voice cloning."""
        return plan.lower() in ["plus", "pro"]

    def can_use_api(self, plan: str) -> bool:
        """Check if plan allows API access."""
        return plan.lower() in ["plus", "pro"]

    def can_use_streaming(self, plan: str) -> bool:
        """Check if plan allows streaming mode."""
        return plan.lower() in ["plus", "pro"]

    def can_use_batch_processing(self, plan: str) -> bool:
        """Check if plan allows batch processing."""
        return plan.lower() == "pro"


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache for singleton pattern.
    """
    return Settings()


def get_subscription_limits() -> SubscriptionLimits:
    """Get subscription limits helper instance."""
    return SubscriptionLimits(get_settings())
