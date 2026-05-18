"""
User service for PhuongAnh-TTS Backend.
Handles user profile management and usage tracking.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.config import get_settings, get_subscription_limits
from core.database import get_database

logger = logging.getLogger(__name__)

# Vietnam timezone for consistent time handling
VIETNAM_TZ = timezone(timedelta(hours=7))


def now_vietnam() -> datetime:
    """Get current datetime in Vietnam timezone (UTC+7)."""
    return datetime.now(VIETNAM_TZ)


def to_vietnam(dt: datetime) -> datetime:
    """Convert a datetime to Vietnam timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
    return dt.astimezone(VIETNAM_TZ)


class UserService:
    """
    User service for profile management and usage tracking.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings = get_settings()
        self.limits = get_subscription_limits()
        self.users = db.users
        self.audio_files = db.audio_files
        self.usage_logs = db.usage_logs

    # ===========================================
    # Profile Management
    # ===========================================

    async def get_profile(self, user_id: str) -> Optional[dict]:
        """
        Get user profile with usage stats.

        Args:
            user_id: User ID

        Returns:
            User profile dict or None
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return None

            # Get usage stats
            usage_stats = await self.get_usage_stats(user_id)
            audio_count = await self.audio_files.count_documents(
                {"user_id": ObjectId(user_id)}
            )

            return {
                "id": str(user["_id"]),
                "email": user["email"],
                "username": user.get("username"),
                "phone": user.get("phone"),
                "subscription_plan": user.get("subscription_plan", "free"),
                "subscription_status": user.get("subscription_status", "active"),
                "subscription_expires_at": to_vietnam(user.get("subscription_expires_at")),
                "is_verified": user.get("is_verified", False),
                "last_login": to_vietnam(user.get("last_login")),
                "created_at": to_vietnam(user.get("created_at")),
                "updated_at": to_vietnam(user.get("updated_at")),
                "total_audio_files": audio_count,
                "usage_stats": usage_stats
            }

        except Exception as e:
            logger.error(f"Get profile error: {e}")
            return None

    async def update_profile(
        self,
        user_id: str,
        username: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Optional[dict]:
        """
        Update user profile.

        Args:
            user_id: User ID
            username: New username (optional)
            phone: New phone (optional)

        Returns:
            Updated user dict or None
        """
        try:
            update_data = {"updated_at": now_vietnam()}

            if username is not None:
                update_data["username"] = username
            if phone is not None:
                update_data["phone"] = phone

            result = await self.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )

            if result.modified_count > 0:
                return await self.get_profile(user_id)
            return None

        except Exception as e:
            logger.error(f"Update profile error: {e}")
            return None

    # ===========================================
    # Usage Tracking
    # ===========================================

    async def get_usage_stats(self, user_id: str) -> dict:
        """
        Get user usage statistics.

        Args:
            user_id: User ID

        Returns:
            Usage stats dict
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            plan = user.get("subscription_plan", "free") if user else "free"

            # Get daily audio count (using Vietnam timezone)
            today = now_vietnam().replace(hour=0, minute=0, second=0, microsecond=0)
            # Convert to UTC for database query
            today_utc = today.astimezone(timezone.utc)
            daily_count = await self.audio_files.count_documents({
                "user_id": ObjectId(user_id),
                "created_at": {"$gte": today_utc}
            })

            # Get monthly character usage
            month_start = now_vietnam().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_start_utc = month_start.astimezone(timezone.utc)
            monthly_logs = await self.usage_logs.find({
                "user_id": ObjectId(user_id),
                "action": "tts_generate",
                "timestamp": {"$gte": month_start_utc}
            }).to_list(length=None)

            monthly_chars = sum(log.get("characters_used", 0) for log in monthly_logs)

            # Get limits based on plan
            daily_limit = self.limits.get_daily_audio_limit(plan)
            monthly_limit = self.limits.get_monthly_chars_limit(plan)
            max_text_length = self.limits.get_max_text_length(plan)

            # Calculate remaining
            daily_remaining = (
                daily_limit - daily_count if daily_limit > 0 else -1
            )
            monthly_remaining = (
                monthly_limit - monthly_chars if monthly_limit > 0 else -1
            )

            return {
                "daily_audio_count": daily_count,
                "monthly_characters": monthly_chars,
                "subscription_plan": plan,
                "daily_audio_limit": daily_limit,
                "monthly_chars_limit": monthly_limit,
                "max_text_length": max_text_length,
                "daily_audio_remaining": daily_remaining,
                "monthly_chars_remaining": monthly_remaining,
                "daily_limit_reached": (
                    0 <= daily_limit <= daily_count if daily_limit > 0 else False
                ),
                "monthly_limit_reached": (
                    0 <= monthly_limit <= monthly_chars if monthly_limit > 0 else False
                )
            }

        except Exception as e:
            logger.error(f"Get usage stats error: {e}")
            return self._default_usage_stats()

    async def log_usage(
        self,
        user_id: str,
        action: str,
        characters_used: int = 0,
        audio_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Log a user action for usage tracking.

        Args:
            user_id: User ID
            action: Action type (tts_generate, download, etc.)
            characters_used: Number of characters used
            audio_id: Related audio ID (optional)
            metadata: Additional metadata (optional)

        Returns:
            True if successful
        """
        try:
            await self.usage_logs.insert_one({
                "user_id": ObjectId(user_id),
                "action": action,
                "characters_used": characters_used,
                "audio_id": ObjectId(audio_id) if audio_id else None,
                "timestamp": now_vietnam(),
                "metadata": metadata or {}
            })
            return True
        except Exception as e:
            logger.error(f"Log usage error: {e}")
            return False

    async def get_daily_usage_history(
        self,
        user_id: str,
        days: int = 7
    ) -> List[dict]:
        """
        Get daily usage history for the past N days.

        Args:
            user_id: User ID
            days: Number of days to retrieve

        Returns:
            List of daily usage dicts
        """
        try:
            start_date = now_vietnam() - timedelta(days=days)
            start_date_utc = start_date.astimezone(timezone.utc)

            pipeline = [
                {
                    "$match": {
                        "user_id": ObjectId(user_id),
                        "timestamp": {"$gte": start_date_utc},
                        "action": {"$in": ["tts_generate", "download"]}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$timestamp"
                            }
                        },
                        "audio_count": {
                            "$sum": {"$cond": [{"$eq": ["$action", "tts_generate"]}, 1, 0]}
                        },
                        "characters_used": {"$sum": "$characters_used"}
                    }
                },
                {"$sort": {"_id": 1}}
            ]

            results = await self.usage_logs.aggregate(pipeline).to_list(length=days)

            return [
                {
                    "date": r["_id"],
                    "audio_count": r["audio_count"],
                    "characters_used": r["characters_used"]
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Get daily usage error: {e}")
            return []

    def _default_usage_stats(self) -> dict:
        """Return default usage stats."""
        return {
            "daily_audio_count": 0,
            "monthly_characters": 0,
            "subscription_plan": "free",
            "daily_audio_limit": self.settings.FREE_DAILY_AUDIO_LIMIT,
            "monthly_chars_limit": self.settings.FREE_MONTHLY_CHARS_LIMIT,
            "max_text_length": self.settings.FREE_MAX_TEXT_LENGTH,
            "daily_audio_remaining": self.settings.FREE_DAILY_AUDIO_LIMIT,
            "monthly_chars_remaining": self.settings.FREE_MONTHLY_CHARS_LIMIT,
            "daily_limit_reached": False,
            "monthly_limit_reached": False
        }

    # ===========================================
    # User Deletion
    # ===========================================

    async def delete_user(self, user_id: str) -> bool:
        """
        Delete user and all associated data.
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful
        """
        try:
            # Delete audio files
            await self.audio_files.delete_many({"user_id": ObjectId(user_id)})
            
            # Delete usage logs
            await self.usage_logs.delete_many({"user_id": ObjectId(user_id)})
            
            # Delete sessions
            await self.db.sessions.delete_many({"user_id": ObjectId(user_id)})
            
            # Delete subscriptions
            await self.db.subscriptions.delete_many({"user_id": ObjectId(user_id)})
            
            # Delete API keys
            await self.db.api_keys.delete_many({"user_id": ObjectId(user_id)})
            
            # Delete user
            result = await self.users.delete_one({"_id": ObjectId(user_id)})
            
            logger.info(f"✓ Deleted user: {user_id}")
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Delete user error: {e}")
            return False


# Factory function
def get_user_service() -> UserService:
    """Get UserService instance."""
    return UserService(get_database())
