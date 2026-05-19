"""
Voice Cloning Service for PhuongAnh-TTS Backend.
Handles voice cloning operations and storage.
"""

import logging
import uuid
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.config import get_settings

logger = logging.getLogger(__name__)

# Vietnam timezone
VIETNAM_TZ = timezone(timedelta(hours=7))


def now_vietnam() -> datetime:
    """Get current datetime in Vietnam timezone (UTC+7)."""
    return datetime.now(VIETNAM_TZ)


class VoiceCloningService:
    """
    Service for voice cloning operations.
    Stores cloned voice metadata and reference audio files.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings = get_settings()
        self.cloned_voices = db.cloned_voices
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure storage directories exist."""
        clone_path = getattr(self.settings, 'CLONE_STORAGE_PATH', './data/clones')
        Path(clone_path).mkdir(parents=True, exist_ok=True)

    def get_clone_storage_path(self) -> Path:
        """Get the storage path for cloned voices."""
        clone_path = getattr(self.settings, 'CLONE_STORAGE_PATH', './data/clones')
        return Path(clone_path)

    async def create_clone(
        self,
        user_id: str,
        audio_data: bytes,
        voice_name: str,
        ref_text: str = ""
    ) -> Tuple[str, dict]:
        """
        Create a new voice clone.
        
        Args:
            user_id: User ID
            audio_data: Reference audio file bytes
            voice_name: Name for the cloned voice
            ref_text: Optional reference text
            
        Returns:
            Tuple of (voice_id, voice_data)
        """
        try:
            # Generate unique voice ID
            voice_id = str(uuid.uuid4())
            
            # Save reference audio
            clone_dir = self.get_clone_storage_path() / user_id
            clone_dir.mkdir(parents=True, exist_ok=True)
            
            audio_filename = f"{voice_id}.wav"
            audio_path = clone_dir / audio_filename
            
            # Write audio file
            with open(audio_path, 'wb') as f:
                f.write(audio_data)
            
            # Create database record
            now = now_vietnam()
            voice_doc = {
                "user_id": ObjectId(user_id),
                "voice_id": voice_id,
                "name": voice_name,
                "audio_path": str(audio_path),
                "filesize": len(audio_data),
                "ref_text": ref_text,
                "status": "ready",
                "created_at": now,
                "updated_at": now,
                "metadata": {
                    "is_active": True,
                    "usage_count": 0
                }
            }
            
            result = await self.cloned_voices.insert_one(voice_doc)
            
            logger.info(f"✓ Voice clone created: {voice_id} for user {user_id}")
            
            # Return voice data
            voice_data = {
                "id": str(result.inserted_id),
                "voice_id": voice_id,
                "name": voice_name,
                "created_at": now
            }
            
            return voice_id, voice_data
            
        except Exception as e:
            logger.error(f"Create voice clone error: {e}")
            raise

    async def get_clone(
        self,
        voice_id: str,
        user_id: str
    ) -> Optional[dict]:
        """
        Get a cloned voice by ID.
        
        Args:
            voice_id: Voice ID
            user_id: User ID (for authorization)
            
        Returns:
            Voice data dict or None
        """
        try:
            voice = await self.cloned_voices.find_one({
                "voice_id": voice_id,
                "user_id": ObjectId(user_id)
            })
            
            if voice:
                voice["_id"] = str(voice["_id"])
                voice["id"] = str(voice.pop("_id"))
                return voice
            return None
            
        except Exception as e:
            logger.error(f"Get voice clone error: {e}")
            return None

    async def list_clones(
        self,
        user_id: str,
        page: int = 1,
        per_page: int = 20
    ) -> Tuple[list, int]:
        """
        List user's cloned voices.
        
        Args:
            user_id: User ID
            page: Page number (1-indexed)
            per_page: Items per page
            
        Returns:
            Tuple of (voice_list, total_count)
        """
        try:
            query = {"user_id": ObjectId(user_id)}
            
            # Get total count
            total = await self.cloned_voices.count_documents(query)
            
            # Get paginated results
            skip = (page - 1) * per_page
            cursor = self.cloned_voices.find(query).sort(
                "created_at", -1
            ).skip(skip).limit(per_page)
            
            voices = []
            async for voice in cursor:
                voices.append({
                    "id": str(voice["_id"]),
                    "voice_id": voice["voice_id"],
                    "name": voice.get("name", "Unnamed"),
                    "status": voice.get("status", "unknown"),
                    "created_at": voice.get("created_at", now_vietnam()),
                    "filesize": voice.get("filesize", 0)
                })
            
            return voices, total
            
        except Exception as e:
            logger.error(f"List clones error: {e}")
            return [], 0

    async def delete_clone(
        self,
        voice_id: str,
        user_id: str
    ) -> bool:
        """
        Delete a cloned voice.
        
        Args:
            voice_id: Voice ID
            user_id: User ID (for authorization)
            
        Returns:
            True if successful
        """
        try:
            # Get voice info
            voice = await self.cloned_voices.find_one({
                "voice_id": voice_id,
                "user_id": ObjectId(user_id)
            })
            
            if not voice:
                return False
            
            # Delete audio file
            audio_path = Path(voice.get("audio_path", ""))
            if audio_path.exists():
                audio_path.unlink()
            
            # Delete database record
            result = await self.cloned_voices.delete_one({
                "voice_id": voice_id
            })
            
            logger.info(f"✓ Deleted voice clone: {voice_id}")
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Delete clone error: {e}")
            return False

    async def increment_usage(self, voice_id: str) -> int:
        """
        Increment usage count for a cloned voice.
        
        Args:
            voice_id: Voice ID
            
        Returns:
            New usage count
        """
        try:
            result = await self.cloned_voices.find_one_and_update(
                {"voice_id": voice_id},
                {
                    "$inc": {"metadata.usage_count": 1},
                    "$set": {"updated_at": now_vietnam()}
                },
                return_document=True
            )
            
            if result:
                return result.get("metadata", {}).get("usage_count", 0)
            return 0
            
        except Exception as e:
            logger.error(f"Increment usage error: {e}")
            return 0

    async def get_clone_audio_path(self, voice_id: str, user_id: str) -> Optional[str]:
        """
        Get the audio file path for a cloned voice.
        
        Args:
            voice_id: Voice ID
            user_id: User ID
            
        Returns:
            Audio file path or None
        """
        voice = await self.get_clone(voice_id, user_id)
        if voice:
            audio_path = voice.get("audio_path")
            if audio_path and Path(audio_path).exists():
                return audio_path
        return None
