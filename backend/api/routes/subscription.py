"""
Subscription API routes for PhuongAnh-TTS Backend.
Handles subscription upgrades and management.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])

# Vietnam timezone
VIETNAM_TZ = timezone(timedelta(hours=7))


def now_vietnam() -> datetime:
    """Get current datetime in Vietnam timezone (UTC+7)."""
    return datetime.now(VIETNAM_TZ)


# CRITICAL FIX: Use unified plan names (plus/pro, not basic/enterprise)
# Plan prices (in VND)
PLAN_PRICES = {
    "free": 0,
    "plus": 199000,
    "pro": 499000,
}

# Plan limits
PLAN_LIMITS = {
    "free": {"daily_audio": 10, "monthly_chars": 10000},
    "plus": {"daily_audio": 100, "monthly_chars": 100000},
    "pro": {"daily_audio": 999999, "monthly_chars": 500000},
}

# Plan hierarchy for upgrade validation
PLAN_HIERARCHY = ["free", "plus", "pro"]


class UpgradeRequest(BaseModel):
    plan: str


class SubscriptionResponse(BaseModel):
    current_plan: str
    new_plan: str
    status: str
    expires_at: Optional[datetime]


def get_db():
    return get_database()


def get_current_user_id(token: str, db: AsyncIOMotorDatabase) -> Optional[str]:
    """Get user ID from token."""
    from jose import jwt, JWTError
    from core.config import get_settings
    settings = get_settings()
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


@router.post("/upgrade", response_model=SubscriptionResponse)
async def upgrade_subscription(
    request: UpgradeRequest,
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Request subscription upgrade.
    Creates a pending subscription request for admin approval.
    """
    from bson import ObjectId

    # Parse token from authorization header
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        raise HTTPException(status_code=401, detail="Authorization required")

    user_id = get_current_user_id(token, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    logger.info(f"Subscription upgrade request: user={user_id}, plan={request.plan}")

    # CRITICAL FIX: Validate plan against unified plan names
    if request.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="Invalid plan")

    # Get current user
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    current_plan = user.get("subscription_plan", "free")

    # Check if upgrading (not downgrading) - use PLAN_HIERARCHY
    current_level = PLAN_HIERARCHY.index(current_plan) if current_plan in PLAN_HIERARCHY else 0
    new_level = PLAN_HIERARCHY.index(request.plan) if request.plan in PLAN_HIERARCHY else 0

    if new_level <= current_level:
        raise HTTPException(status_code=400, detail="Cannot downgrade or stay on same plan")

    # Check if there's already a pending request
    existing = await db.subscriptions.find_one({
        "user_id": ObjectId(user_id),
        "status": "pending"
    })
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending subscription request")

    # Create pending subscription request
    now = now_vietnam()
    result = await db.subscriptions.insert_one({
        "user_id": ObjectId(user_id),
        "plan": request.plan,
        "status": "pending",
        "requested_at": now,
        "billing_cycle": "monthly",
        "price": PLAN_PRICES[request.plan],
    })

    logger.info(f"✓ Created pending subscription: {result.inserted_id}")

    return SubscriptionResponse(
        current_plan=current_plan,
        new_plan=request.plan,
        status="pending",
        expires_at=None
    )


@router.get("/limits")
async def get_plan_limits(
    plan: str = "free"
):
    """Get limits for a specific plan."""
    if plan not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    return {
        "plan": plan,
        "limits": PLAN_LIMITS[plan],
        "price": PLAN_PRICES[plan]
    }


@router.get("/pricing")
async def get_pricing():
    """Get all plan pricing with unified plan names."""
    return {
        "plans": [
            {
                "id": "free",
                "name": "Free",
                "price": 0,
                "price_display": "Miễn phí",
                "limits": PLAN_LIMITS["free"]
            },
            {
                "id": "plus",
                "name": "Plus",
                "price": PLAN_PRICES["plus"],
                "price_display": "199,000đ/tháng",
                "limits": PLAN_LIMITS["plus"]
            },
            {
                "id": "pro",
                "name": "Pro",
                "price": PLAN_PRICES["pro"],
                "price_display": "499,000đ/tháng",
                "limits": PLAN_LIMITS["pro"]
            }
        ]
    }


@router.get("/me")
async def get_my_subscription(
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Get current user's subscription status."""
    from bson import ObjectId

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization[7:]
    user_id = get_current_user_id(token, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan = user.get("subscription_plan", "free")
    status = user.get("subscription_status", "active")
    expires_at = user.get("subscription_expires_at")
    started_at = user.get("subscription_started_at")

    # Check expiration
    now = now_vietnam()
    remaining_days = None
    if expires_at:
        expires_vn = expires_at
        if expires_vn.tzinfo is None:
            expires_vn = expires_vn.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
        if now < expires_vn:
            remaining_days = (expires_vn - now).days
        elif plan != "free":
            status = "expired"

    return {
        "plan": plan,
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_days": remaining_days,
        "price": PLAN_PRICES.get(plan, 0)
    }
