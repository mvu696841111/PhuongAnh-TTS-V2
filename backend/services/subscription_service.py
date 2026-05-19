"""
Subscription Service for PhuongAnh-TTS Backend.
Handles subscription plan limits and quota management.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from pymongo.database import Database
from bson import ObjectId

from models.schemas.subscription import PlanType, PlanLimits, FeatureFlags

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing subscription limits and features."""
    
    def __init__(self, db: Database):
        self.db = db
        self.plans_collection = db.subscriptions_plans
        self.users_collection = db.users
        self.audio_collection = db.audio_files
    
    async def get_user_plan(self, user_id: Optional[str], session_id: Optional[str] = None) -> Tuple[Dict, Dict, Dict]:
        """
        Get user's plan limits and features.

        Returns:
            Tuple of (limits, features, plan_info)
        """
        default_limits = {
            "max_chars_per_month": 5000,
            "max_audio_per_day": 10,
            "max_text_length": 500,
            "max_audio_duration": 30,
            "max_audio_per_month": 50,
            "max_concurrent_jobs": 1,
        }
        default_features = {
            "voice_cloning": False,
            "long_text": False,
            "priority_queue": False,
            "api_access": False,
            "watermark_free": True,
            "custom_voices": False,
            "batch_processing": False,
            "analytics": False,
            "support_priority": "email",
        }

        if not user_id and not session_id:
            return default_limits, default_features, {"plan_type": "free", "name": "Miễn phí"}

        try:
            if user_id:
                user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            else:
                user = await self.users_collection.find_one({"session_id": session_id})

            if not user:
                return default_limits, default_features, {"plan_type": "free", "name": "Miễn phí"}

            plan_type = user.get("plan_type", PlanType.FREE.value)
            plan = await self.plans_collection.find_one({
                "plan_type": plan_type,
                "status": "active"
            })

            if not plan:
                plan = await self.plans_collection.find_one({
                    "plan_type": PlanType.FREE.value,
                    "status": "active"
                })

            if not plan:
                return default_limits, default_features, {"plan_type": "free", "name": "Miễn phí"}

            return (
                plan.get("limits") or default_limits,
                plan.get("features") or default_features,
                {
                    "plan_type": plan.get("plan_type", "free"),
                    "name": plan.get("name", "Unknown"),
                    "id": str(plan.get("_id", "")),
                }
            )
        except Exception as e:
            logger.error(f"Error getting user plan: {e}")
            return default_limits, default_features, {"plan_type": "free", "name": "Miễn phí"}
    
    async def check_limits(
        self,
        text: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        duration: float = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if user is within their plan limits.

        Returns:
            Tuple of (allowed, error_message, quota_info)
        """
        limits, features, plan_info = await self.get_user_plan(user_id, session_id)
        now = datetime.utcnow()

        # Get current usage
        month_start = datetime(now.year, now.month, 1)
        today_start = datetime(now.year, now.month, now.day)

        text_length = len(text)

        # Check text length limit
        max_text_length = limits.get("max_text_length", 500)
        if text_length > max_text_length:
            return False, f"Văn bản quá dài. Tối đa {max_text_length} ký tự cho gói {plan_info['name']}.", {
                "limit_type": "text_length",
                "limit": max_text_length,
                "current": text_length,
            }

        # Check audio duration limit
        max_duration = limits.get("max_audio_duration", 30)
        if duration > max_duration:
            return False, f"Audio quá dài. Tối đa {max_duration} giây cho gói {plan_info['name']}.", {
                "limit_type": "audio_duration",
                "limit": max_duration,
                "current": duration,
            }

        # Query for usage stats
        query_user = ObjectId(user_id) if user_id else session_id
        user_id_field = "user_id" if user_id else "session_id"

        # Check daily audio limit
        daily_audio = await self.audio_collection.count_documents({
            user_id_field: query_user,
            "created_at": {"$gte": today_start}
        })
        max_audio_per_day = limits.get("max_audio_per_day", 10)
        if max_audio_per_day > 0 and daily_audio >= max_audio_per_day:
            return False, f"Đã đạt giới hạn {max_audio_per_day} audio/ngày cho gói {plan_info['name']}. Vui lòng thử lại sau.", {
                "limit_type": "daily_audio",
                "limit": max_audio_per_day,
                "current": daily_audio,
            }

        # Check monthly character limit
        monthly_chars_result = self.audio_collection.aggregate([
            {"$match": {
                user_id_field: query_user,
                "created_at": {"$gte": month_start}
            }},
            {"$group": {
                "_id": None,
                "total_chars": {"$sum": {"$strLenCP": "$text_input"}}
            }}
        ])
        monthly_chars = await monthly_chars_result.to_list(length=1)
        monthly_chars = monthly_chars[0]["total_chars"] if monthly_chars else 0

        max_chars_per_month = limits.get("max_chars_per_month", 5000)
        if max_chars_per_month > 0 and (monthly_chars + text_length) > max_chars_per_month:
            chars_remaining = max(0, max_chars_per_month - monthly_chars)
            return False, f"Đã đạt giới hạn {max_chars_per_month} ký tự/tháng cho gói {plan_info['name']}. Còn lại: {chars_remaining} ký tự.", {
                "limit_type": "monthly_chars",
                "limit": max_chars_per_month,
                "current": monthly_chars,
                "remaining": chars_remaining,
            }

        # Check monthly audio limit
        monthly_audio = await self.audio_collection.count_documents({
            user_id_field: query_user,
            "created_at": {"$gte": month_start}
        })
        max_audio_per_month = limits.get("max_audio_per_month", 50)
        if max_audio_per_month > 0 and monthly_audio >= max_audio_per_month:
            return False, f"Đã đạt giới hạn {max_audio_per_month} audio/tháng cho gói {plan_info['name']}.", {
                "limit_type": "monthly_audio",
                "limit": max_audio_per_month,
                "current": monthly_audio,
            }

        return True, "", {
            "plan": plan_info,
            "usage": {
                "chars_this_month": monthly_chars,
                "audio_this_month": monthly_audio,
                "audio_today": daily_audio,
            },
            "limits": limits,
            "remaining": {
                "chars": max(0, max_chars_per_month - monthly_chars - text_length) if max_chars_per_month > 0 else -1,
                "audio_today": max(0, max_audio_per_day - daily_audio - 1) if max_audio_per_day > 0 else -1,
            }
        }
    
    async def get_quota_info(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get current quota information for a user."""
        limits, features, plan_info = await self.get_user_plan(user_id, session_id)
        now = datetime.utcnow()

        month_start = datetime(now.year, now.month, 1)
        today_start = datetime(now.year, now.month, now.day)

        query_user = ObjectId(user_id) if user_id else session_id
        user_id_field = "user_id" if user_id else "session_id"

        daily_audio = await self.audio_collection.count_documents({
            user_id_field: query_user,
            "created_at": {"$gte": today_start}
        })

        monthly_stats = self.audio_collection.aggregate([
            {"$match": {user_id_field: query_user, "created_at": {"$gte": month_start}}},
            {"$group": {
                "_id": None,
                "total_chars": {"$sum": {"$strLenCP": "$text_input"}},
                "total_audio": {"$sum": 1}
            }}
        ])
        stats_list = await monthly_stats.to_list(length=1)
        stats = stats_list[0] if stats_list else {"total_chars": 0, "total_audio": 0}

        max_chars = limits.get("max_chars_per_month", 0)
        max_audio_day = limits.get("max_audio_per_day", 0)
        max_audio_month = limits.get("max_audio_per_month", 0)

        return {
            "plan": plan_info,
            "features": features,
            "usage": {
                "chars_this_month": stats.get("total_chars", 0),
                "audio_this_month": stats.get("total_audio", 0),
                "audio_today": daily_audio,
            },
            "limits": {
                "chars_per_month": max_chars,
                "audio_per_day": max_audio_day,
                "audio_per_month": max_audio_month,
                "text_length": limits.get("max_text_length", 500),
                "audio_duration": limits.get("max_audio_duration", 30),
            },
            "remaining": {
                "chars": max(0, max_chars - stats.get("total_chars", 0)) if max_chars > 0 else -1,
                "audio_today": max(0, max_audio_day - daily_audio) if max_audio_day > 0 else -1,
                "audio_month": max(0, max_audio_month - stats.get("total_audio", 0)) if max_audio_month > 0 else -1,
            },
            "next_reset": (month_start + timedelta(days=32)).replace(day=1).isoformat(),
        }
    
    async def check_feature_access(
        self,
        feature: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Check if user has access to a specific feature."""
        limits, features, plan_info = await self.get_user_plan(user_id, session_id)
        
        feature_map = {
            "voice_cloning": "Voice Cloning",
            "long_text": "Xử lý văn bản dài",
            "priority_queue": "Ưu tiên xử lý",
            "api_access": "API Access",
            "watermark_free": "Không watermark",
            "custom_voices": "Tạo giọng tùy chỉnh",
            "batch_processing": "Xử lý hàng loạt",
            "analytics": "Thống kê chi tiết",
        }
        
        if feature not in features:
            return False, f"Tính năng không hợp lệ"
        
        if not features.get(feature, False):
            feature_name = feature_map.get(feature, feature)
            return False, f"Tính năng '{feature_name}' chỉ có ở gói cao hơn. Vui lòng nâng cấp gói."
        
        return True, ""
