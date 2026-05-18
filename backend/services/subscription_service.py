"""
Subscription service for PhuongAnh-TTS Backend.
Handles subscription plans, upgrades, and billing.
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


# Plan hierarchy for upgrade validation (higher index = higher tier)
PLAN_HIERARCHY = ["free", "plus", "pro"]

# Plan prices (VND)
PLAN_PRICES = {
    "free": 0,
    "plus": 199000,
    "pro": 499000,
}


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
        Get user's current subscription with accurate status.

        Args:
            user_id: User ID

        Returns:
            Subscription dict or None
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return None

            plan_id = user.get("subscription_plan", "free")
            expires_at = user.get("subscription_expires_at")
            status = user.get("subscription_status", "active")

            # Check if subscription is expired
            now = now_vietnam()
            expires_at_vn = to_vietnam(expires_at) if expires_at else None

            # Determine actual status
            if plan_id != "free" and expires_at_vn:
                if now > expires_at_vn:
                    status = "expired"
                elif (expires_at_vn - now).days <= 3:
                    status = "expiring_soon"
            elif plan_id == "free":
                status = "active"  # Free plan never expires

            # Calculate remaining days
            remaining_days = None
            if plan_id != "free" and expires_at_vn:
                if now <= expires_at_vn:
                    remaining_days = (expires_at_vn - now).days
                else:
                    remaining_days = 0

            plan = await self.plans.find_one({"_id": plan_id})
            features = plan.get("features", {}) if plan else {}

            return {
                "current_plan": plan_id,
                "status": status,
                "started_at": to_vietnam(user.get("created_at")),
                "expires_at": expires_at_vn,
                "remaining_days": remaining_days,
                "features": features,
                "can_upgrade": True,
                "upgrade_available": self._get_upgrade_options(plan_id),
                "price": PLAN_PRICES.get(plan_id, 0)
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
        billing_cycle: str = "monthly",
        payment_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upgrade user subscription with proper expiration handling.

        Args:
            user_id: User ID
            new_plan: Target plan ID
            billing_cycle: Monthly or yearly
            payment_id: Optional payment ID for reference

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

            now = now_vietnam()

            # Calculate expiration
            if billing_cycle == "yearly":
                expires_at = now + timedelta(days=365)
            else:
                expires_at = now + timedelta(days=30)

            # Check if user already has an active subscription to extend
            current_expires = user.get("subscription_expires_at")
            current_expires_vn = to_vietnam(current_expires) if current_expires else None

            # If current subscription is still active, extend from current expiration
            # Otherwise, start from now
            if current_expires_vn and current_expires_vn > now:
                start_date = current_expires_vn
                new_expires_at = current_expires_vn + timedelta(days=30 if billing_cycle == "monthly" else 365)
            else:
                start_date = now
                new_expires_at = expires_at

            # Update user
            await self.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "subscription_plan": new_plan,
                        "subscription_status": "active",
                        "subscription_expires_at": new_expires_at,
                        "subscription_started_at": start_date,
                        "updated_at": now
                    }
                }
            )

            # Create subscription record
            await self.subscriptions.insert_one({
                "user_id": ObjectId(user_id),
                "plan": new_plan,
                "started_at": start_date,
                "expires_at": new_expires_at,
                "auto_renew": billing_cycle == "yearly",
                "billing_cycle": billing_cycle,
                "payment_id": payment_id,
                "payment_history": [{
                    "date": now,
                    "amount": PLAN_PRICES.get(new_plan, 0) * (12 if billing_cycle == "yearly" else 1),
                    "billing_cycle": billing_cycle,
                    "status": "completed"
                }],
                "status": "active"
            })

            # Log upgrade with Vietnam timezone
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
                "effective_date": start_date,
                "expires_at": new_expires_at,
                "remaining_days": (new_expires_at - now).days if new_expires_at > now else 0
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
            expires_at = user.get("subscription_expires_at")
            now = now_vietnam()
            expires_at_vn = to_vietnam(expires_at) if expires_at else None

            # Check if expired
            if plan != "free" and expires_at_vn:
                if now > expires_at_vn:
                    # Downgrade to free
                    await self.users.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "subscription_plan": "free",
                                "subscription_status": "expired",
                                "updated_at": now
                            }
                        }
                    )
                    logger.info(f"User {user_id} subscription expired, downgraded to free")
                    return False

            return user.get("subscription_status", "active") == "active"

        except Exception as e:
            logger.error(f"Check subscription status error: {e}")
            return True  # Assume active on error

    async def renew_subscription(
        self,
        user_id: str,
        billing_cycle: str = "monthly",
        payment_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Renew an existing subscription.

        Args:
            user_id: User ID
            billing_cycle: Monthly or yearly
            payment_id: Payment record ID

        Returns:
            Result dict
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return {"success": False, "message": "User not found"}

            plan = user.get("subscription_plan", "free")
            if plan == "free":
                return {"success": False, "message": "Free plan cannot be renewed"}

            now = now_vietnam()
            current_expires = user.get("subscription_expires_at")
            current_expires_vn = to_vietnam(current_expires) if current_expires else None

            # Calculate new expiration
            extension = timedelta(days=30 if billing_cycle == "monthly" else 365)

            if current_expires_vn and current_expires_vn > now:
                # Extend from current expiration
                new_expires_at = current_expires_vn + extension
            else:
                # Start fresh from now
                new_expires_at = now + extension

            # Update user
            await self.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "subscription_status": "active",
                        "subscription_expires_at": new_expires_at,
                        "updated_at": now
                    }
                }
            )

            # Log renewal
            await self.db.usage_logs.insert_one({
                "user_id": ObjectId(user_id),
                "action": "renew",
                "timestamp": now,
                "metadata": {
                    "plan": plan,
                    "billing_cycle": billing_cycle,
                    "new_expires_at": str(new_expires_at)
                }
            })

            logger.info(f"✓ User {user_id} renewed subscription to {plan}")

            return {
                "success": True,
                "message": f"Subscription renewed successfully",
                "expires_at": new_expires_at,
                "remaining_days": (new_expires_at - now).days
            }

        except Exception as e:
            logger.error(f"Renew subscription error: {e}")
            return {"success": False, "message": "Renewal failed"}

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
