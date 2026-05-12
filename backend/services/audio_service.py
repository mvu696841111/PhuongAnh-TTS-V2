"""
Audio service for PhuongAnh-TTS Backend.
Handles TTS generation, audio storage, and management.
"""

import os
import logging
import uuid
import aiofiles
from datetime import datetime
from typing import Optional, List, Tuple
from pathlib import Path
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.config import get_settings, get_subscription_limits
from core.database import get_database

logger = logging.getLogger(__name__)


class AudioService:
    """
    Audio service for TTS generation and storage management.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings = get_settings()
        self.limits = get_subscription_limits()
        self.audio_files = db.audio_files
        self.usage_logs = db.usage_logs
        
        # Ensure directories exist
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure storage directories exist."""
        Path(self.settings.AUDIO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
        Path(self.settings.TEMP_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

    # ===========================================
    # Storage Management
    # ===========================================

    def get_user_audio_dir(self, user_id: str) -> Path:
        """Get user's audio storage directory."""
        user_dir = Path(self.settings.AUDIO_STORAGE_PATH) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    async def save_audio(
        self,
        user_id: str,
        audio_data: bytes,
        filename: str,
        text_input: str,
        voice_id: str,
        duration: float,
        format: str = "wav"
    ) -> Optional[dict]:
        """
        Save audio file and create database record.
        
        Args:
            user_id: User ID
            audio_data: Audio file bytes
            filename: Original filename
            text_input: Original text input
            voice_id: Voice ID used
            duration: Audio duration in seconds
            format: Audio format
            
        Returns:
            Audio file dict or None
        """
        try:
            # Generate unique filename
            audio_id = str(uuid.uuid4())
            safe_filename = f"{audio_id}.{format.lower()}"
            
            # Determine if watermark needed
            user = await self.db.users.find_one({"_id": ObjectId(user_id)})
            plan = user.get("subscription_plan", "free") if user else "free"
            needs_watermark = self.limits.has_watermark(plan)
            
            # For now, skip actual watermarking (would integrate with audio processing)
            filepath = self.get_user_audio_dir(user_id) / safe_filename
            
            # Save file
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(audio_data)
            
            filesize = len(audio_data)
            
            # Create database record
            now = datetime.utcnow()
            audio_doc = {
                "user_id": ObjectId(user_id),
                "filename": filename,
                "filepath": str(filepath),
                "filesize": filesize,
                "duration": duration,
                "text_input": text_input,
                "voice_id": voice_id,
                "format": format.lower(),
                "is_watermarked": needs_watermark,
                "download_count": 0,
                "created_at": now,
                "metadata": {
                    "audio_id": audio_id,
                    "plan_at_creation": plan
                }
            }
            
            result = await self.audio_files.insert_one(audio_doc)
            
            logger.info(f"✓ Saved audio: {audio_id} for user {user_id}")
            
            return {
                "id": str(result.inserted_id),
                "audio_id": audio_id,
                "filename": filename,
                "filesize": filesize,
                "duration": duration,
                "is_watermarked": needs_watermark,
                "created_at": now
            }
            
        except Exception as e:
            logger.error(f"Save audio error: {e}")
            return None

    async def get_audio(self, audio_id: str, user_id: str) -> Optional[dict]:
        """
        Get audio file info by ID.
        
        Args:
            audio_id: Audio file ID
            user_id: User ID (for authorization)
            
        Returns:
            Audio file dict or None
        """
        try:
            audio = await self.audio_files.find_one({
                "_id": ObjectId(audio_id),
                "user_id": ObjectId(user_id)
            })
            
            if audio:
                audio["_id"] = str(audio["_id"])
                audio["id"] = str(audio.pop("_id"))
                return audio
            return None
            
        except Exception as e:
            logger.error(f"Get audio error: {e}")
            return None

    async def list_user_audios(
        self,
        user_id: str,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[List[dict], int]:
        """
        List user's audio files with pagination.
        
        Args:
            user_id: User ID
            page: Page number (1-indexed)
            per_page: Items per page
            
        Returns:
            Tuple of (audio_list, total_count)
        """
        try:
            # Build query
            query = {"user_id": ObjectId(user_id)}
            
            # Get total count
            total = await self.audio_files.count_documents(query)
            
            # Get paginated results
            skip = (page - 1) * per_page
            cursor = self.audio_files.find(query).sort(
                "created_at", -1
            ).skip(skip).limit(per_page)
            
            audios = []
            async for audio in cursor:
                audio["id"] = str(audio.pop("_id"))
                audio["user_id"] = str(audio.pop("user_id"))
                audios.append(audio)
            
            return audios, total
            
        except Exception as e:
            logger.error(f"List audios error: {e}")
            return [], 0

    async def delete_audio(self, audio_id: str, user_id: str) -> bool:
        """
        Delete audio file and database record.
        
        Args:
            audio_id: Audio file ID
            user_id: User ID (for authorization)
            
        Returns:
            True if successful
        """
        try:
            # Get audio info
            audio = await self.audio_files.find_one({
                "_id": ObjectId(audio_id),
                "user_id": ObjectId(user_id)
            })
            
            if not audio:
                return False
            
            # Delete file
            filepath = Path(audio["filepath"])
            if filepath.exists():
                filepath.unlink()
            
            # Delete record
            result = await self.audio_files.delete_one({
                "_id": ObjectId(audio_id)
            })
            
            logger.info(f"✓ Deleted audio: {audio_id}")
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Delete audio error: {e}")
            return False

    async def increment_download_count(self, audio_id: str) -> int:
        """
        Increment audio download count.
        
        Args:
            audio_id: Audio file ID
            
        Returns:
            New download count
        """
        try:
            result = await self.audio_files.find_one_and_update(
                {"_id": ObjectId(audio_id)},
                {"$inc": {"download_count": 1}},
                return_document=True
            )
            return result.get("download_count", 0) if result else 0
        except Exception as e:
            logger.error(f"Increment download error: {e}")
            return 0

    # ===========================================
    # Usage Limits Check
    # ===========================================

    async def check_usage_limits(
        self,
        user_id: str,
        text_length: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if user can generate audio based on usage limits.
        
        Args:
            user_id: User ID
            text_length: Length of text to generate
            
        Returns:
            Tuple of (can_generate, error_message)
        """
        try:
            # Get user plan
            user = await self.db.users.find_one({"_id": ObjectId(user_id)})
            plan = user.get("subscription_plan", "free") if user else "free"
            
            # Get limits
            limits = self.limits
            
            # Check text length limit
            max_text_length = limits.get_max_text_length(plan)
            if text_length > max_text_length:
                return False, f"Text too long. Maximum is {max_text_length} characters for {plan} plan."
            
            # Check daily audio limit
            daily_limit = limits.get_daily_audio_limit(plan)
            if daily_limit > 0:
                today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                today_count = await self.audio_files.count_documents({
                    "user_id": ObjectId(user_id),
                    "created_at": {"$gte": today}
                })
                
                if today_count >= daily_limit:
                    return False, f"Daily audio limit reached ({daily_limit}). Upgrade your plan for more."
            
            # Check monthly character limit
            month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly_logs = await self.usage_logs.find({
                "user_id": ObjectId(user_id),
                "action": "tts_generate",
                "timestamp": {"$gte": month_start}
            }).to_list(length=None)
            
            monthly_chars = sum(log.get("characters_used", 0) for log in monthly_logs)
            monthly_limit = limits.get_monthly_chars_limit(plan)
            
            if monthly_chars + text_length > monthly_limit:
                remaining = max(0, monthly_limit - monthly_chars)
                return False, f"Monthly character limit reached. You have {remaining} characters remaining."
            
            return True, None
            
        except Exception as e:
            logger.error(f"Check usage limits error: {e}")
            return False, "Failed to check usage limits"

    # ===========================================
    # Temporary Files
    # ===========================================

    async def cleanup_temp_files(self, max_age_hours: int = 24) -> int:
        """
        Clean up old temporary files.
        
        Args:
            max_age_hours: Maximum age in hours before deletion
            
        Returns:
            Number of files deleted
        """
        try:
            temp_path = Path(self.settings.TEMP_STORAGE_PATH)
            if not temp_path.exists():
                return 0
            
            deleted = 0
            max_age_seconds = max_age_hours * 3600
            now = datetime.utcnow().timestamp()
            
            for file in temp_path.rglob("*"):
                if file.is_file():
                    file_age = now - file.stat().st_mtime
                    if file_age > max_age_seconds:
                        file.unlink()
                        deleted += 1
            
            if deleted > 0:
                logger.info(f"✓ Cleaned up {deleted} temp files")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Cleanup temp files error: {e}")
            return 0


# Factory function
def get_audio_service() -> AudioService:
    """Get AudioService instance."""
    return AudioService(get_database())
