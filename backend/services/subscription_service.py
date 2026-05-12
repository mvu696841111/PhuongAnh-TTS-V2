"""
Subscription service for PhuongAnh-TTS Backend.
Handles subscription plans, upgrades, and billing.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.config import get_settings, get_subscription_limits
from core.database import get_database

logger = logging.getLogger(__name__)


class SubscriptionService:
    """
    Subscription service for managing user plans.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings = get_settings()
        self.limits = get_subscription_limits()
        self.users = db.users
        self.subscriptions = db.subscriptions
        self.plans = db.subscriptions_plans

    # ===========================================
    # Plan Information
    # ===========================================

    async def get_available_plans(self) -> List[dict]:
        """
        Get all available subscription plans.
        
        Returns:
            List of plan dictionaries
        """
        try:
            plans = await self.plans.find({}).to_list(length=None)
            
            result = []
            for plan in plans:
                result.append({
                    "id": plan["_id"],
                    "name": plan["name"],
                    "description": plan["description"],
                    "price_monthly": plan["price_monthly"],
                    "price_yearly": plan["price_yearly"],
                    "features": plan["features"],
                    "permissions": plan.get("permissions", []),
                    "is_popular": plan["_id"] == "plus"
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Get plans error: {e}")
            return []

    async def get_plan_info(self, plan_id: str) -> Optional[dict]:
        """
        Get information about a specific plan.
        
        Args:
            plan_id: Plan ID (free, plus, pro)
            
        Returns:
            Plan dict or None
        """
        try:
            plan = await self.plans.find_one({"_id": plan_id})
            if plan:
                plan["id"] = plan.pop("_id")
                return plan
            return None
        except Exception as e:
            logger.error(f"Get plan info error: {e}")
            return None

    # ===========================================
    # User Subscription
    # ===========================================

    async def get_user_subscription(self, user_id: str) -> Optional[dict]:
        """
        Get user's current subscription.
        
        Args:
            user_id: User ID
            
        Returns:
            Subscription dict or None
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return None
            
            plan = await self.plans.find_one({"_id": user.get("subscription_plan", "free")})
            features = plan.get("features", {}) if plan else {}
            
            return {
                "current_plan": user.get("subscription_plan", "free"),
                "status": user.get("subscription_status", "active"),
                "started_at": user.get("created_at"),
                "expires_at": user.get("subscription_expires_at"),
                "features": features,
                "can_upgrade": True,
                "upgrade_available": self._get_upgrade_options(user.get("subscription_plan", "free"))
            }
            
        except Exception as e:
            logger.error(f"Get subscription error: {e}")
            return None

    def _get_upgrade_options(self, current_plan: str) -> List[str]:
        """Get available plan upgrades from current plan."""
        hierarchy = {"free": ["plus", "pro"], "plus": ["pro"], "pro": []}
        return hierarchy.get(current_plan, [])

    async def upgrade_subscription(
        self,
        user_id: str,
        new_plan: str,
        billing_cycle: str = "monthly"
    ) -> Dict[str, Any]:
        """
        Upgrade user subscription.
        
        Args:
            user_id: User ID
            new_plan: Target plan ID
            billing_cycle: Monthly or yearly
            
        Returns:
            Result dict with success status
        """
        try:
            # Get current user
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return {"success": False, "message": "User not found"}
            
            current_plan = user.get("subscription_plan", "free")
            
            # Check if upgrade is valid
            if new_plan not in self._get_upgrade_options(current_plan):
                return {
                    "success": False,
                    "message": f"Cannot upgrade from {current_plan} to {new_plan}"
                }
            
            # Get plan info
            plan_info = await self.plans.find_one({"_id": new_plan})
            if not plan_info:
                return {"success": False, "message": "Plan not found"}
            
            # Calculate expiration
            now = datetime.utcnow()
            if billing_cycle == "yearly":
                expires_at = now + timedelta(days=365)
            else:
                expires_at = now + timedelta(days=30)
            
            # Update user
            await self.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "subscription_plan": new_plan,
                        "subscription_status": "active",
                        "subscription_expires_at": expires_at,
                        "updated_at": now
                    }
                }
            )
            
            # Create subscription record
            await self.subscriptions.insert_one({
                "user_id": ObjectId(user_id),
                "plan": new_plan,
                "started_at": now,
                "expires_at": expires_at,
                "auto_renew": billing_cycle == "yearly",
                "payment_history": [{
                    "date": now,
                    "amount": plan_info.get("price_monthly" if billing_cycle == "monthly" else "price_yearly", 0),
                    "billing_cycle": billing_cycle,
                    "status": "completed"
                }],
                "status": "active"
            })
            
            # Log upgrade
            await self.db.usage_logs.insert_one({
                "user_id": ObjectId(user_id),
                "action": "upgrade",
                "timestamp": now,
                "metadata": {
                    "from_plan": current_plan,
                    "to_plan": new_plan,
                    "billing_cycle": billing_cycle
                }
            })
            
            logger.info(f"✓ User {user_id} upgraded to {new_plan}")
            
            return {
                "success": True,
                "message": f"Successfully upgraded to {plan_info['name']}",
                "new_plan": new_plan,
                "effective_date": now,
                "expires_at": expires_at
            }
            
        except Exception as e:
            logger.error(f"Upgrade subscription error: {e}")
            return {"success": False, "message": "Upgrade failed"}

    async def check_subscription_status(self, user_id: str) -> bool:
        """
        Check and update subscription status if expired.
        
        Args:
            user_id: User ID
            
        Returns:
            True if subscription is active
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False
            
            plan = user.get("subscription_plan", "free")
            status = user.get("subscription_status", "active")
            expires_at = user.get("subscription_expires_at")
            
            # Check if expired
            if plan != "free" and expires_at:
                if datetime.utcnow() > expires_at:
                    # Downgrade to free
                    await self.users.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "subscription_plan": "free",
                                "subscription_status": "expired",
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    logger.info(f"User {user_id} subscription expired, downgraded to free")
                    return False
            
            return status == "active"
            
        except Exception as e:
            logger.error(f"Check subscription status error: {e}")
            return True  # Assume active on error

    # ===========================================
    # Permission Checks
    # ===========================================

    async def has_permission(self, user_id: str, permission: str) -> bool:
        """
        Check if user has a specific permission.
        
        Args:
            user_id: User ID
            permission: Permission string (e.g., 'api:access')
            
        Returns:
            True if user has permission
        """
        try:
            await self.check_subscription_status(user_id)
            
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False
            
            plan_id = user.get("subscription_plan", "free")
            plan = await self.plans.find_one({"_id": plan_id})
            
            if not plan:
                return False
            
            permissions = plan.get("permissions", [])
            return permission in permissions
            
        except Exception as e:
            logger.error(f"Check permission error: {e}")
            return False


# Factory function
def get_subscription_service() -> SubscriptionService:
    """Get SubscriptionService instance."""
    return SubscriptionService(get_database())
