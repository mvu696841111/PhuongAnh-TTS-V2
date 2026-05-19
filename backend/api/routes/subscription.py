"""
Subscription routes for PhuongAnh-TTS Backend.
Handles subscription plan management and user subscription info.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pymongo import MongoClient
from bson import ObjectId

from models.schemas.subscription import (
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanResponse,
    PlanListResponse,
    UserSubscriptionInfo,
    PlanLimits,
    FeatureFlags,
    PlanPricing,
    PlanStatus,
    PlanType,
)
from api.dependencies import get_db, RequirePermission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subscription", tags=["subscription"])


def get_default_plans() -> List[SubscriptionPlanCreate]:
    """Return default subscription plans."""
    return [
        SubscriptionPlanCreate(
            name="Miễn phí",
            plan_type=PlanType.FREE,
            description="Gói cơ bản dành cho người dùng mới",
            is_default=True,
            sort_order=1,
            limits=PlanLimits(
                max_chars_per_month=5000,
                max_audio_per_day=10,
                max_text_length=500,
                max_audio_duration=30,
                max_audio_per_month=50,
                max_concurrent_jobs=1,
            ),
            features=FeatureFlags(
                voice_cloning=False,
                long_text=False,
                priority_queue=False,
                api_access=False,
                watermark_free=False,
                custom_voices=False,
                batch_processing=False,
                analytics=False,
            ),
            pricing=PlanPricing(monthly_price=0, yearly_price=0),
        ),
        SubscriptionPlanCreate(
            name="Cơ bản",
            plan_type=PlanType.BASIC,
            description="Gói cơ bản với nhiều tính năng hơn",
            sort_order=2,
            limits=PlanLimits(
                max_chars_per_month=50000,
                max_audio_per_day=50,
                max_text_length=2000,
                max_audio_duration=120,
                max_audio_per_month=500,
                max_concurrent_jobs=2,
            ),
            features=FeatureFlags(
                voice_cloning=False,
                long_text=True,
                priority_queue=False,
                api_access=False,
                watermark_free=True,
                custom_voices=False,
                batch_processing=False,
                analytics=False,
            ),
            pricing=PlanPricing(monthly_price=99000, yearly_price=990000),
        ),
        SubscriptionPlanCreate(
            name="Tiêu chuẩn",
            plan_type=PlanType.STANDARD,
            description="Gói tiêu chuẩn cho người dùng thường xuyên",
            sort_order=3,
            limits=PlanLimits(
                max_chars_per_month=200000,
                max_audio_per_day=200,
                max_text_length=5000,
                max_audio_duration=300,
                max_audio_per_month=2000,
                max_concurrent_jobs=5,
            ),
            features=FeatureFlags(
                voice_cloning=True,
                long_text=True,
                priority_queue=True,
                api_access=False,
                watermark_free=True,
                custom_voices=False,
                batch_processing=False,
                analytics=True,
            ),
            pricing=PlanPricing(monthly_price=299000, yearly_price=2990000),
        ),
        SubscriptionPlanCreate(
            name="Cao cấp",
            plan_type=PlanType.PREMIUM,
            description="Gói cao cấp với tất cả tính năng",
            sort_order=4,
            limits=PlanLimits(
                max_chars_per_month=1000000,
                max_audio_per_day=1000,
                max_text_length=10000,
                max_audio_duration=600,
                max_audio_per_month=10000,
                max_concurrent_jobs=10,
            ),
            features=FeatureFlags(
                voice_cloning=True,
                long_text=True,
                priority_queue=True,
                api_access=True,
                watermark_free=True,
                custom_voices=True,
                batch_processing=True,
                analytics=True,
                support_priority="priority",
            ),
            pricing=PlanPricing(monthly_price=799000, yearly_price=7990000),
        ),
    ]


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    include_inactive: bool = False,
    db=Depends(get_db),
):
    """List all subscription plans."""
    query = {}
    if not include_inactive:
        query["status"] = PlanStatus.ACTIVE.value

    plans = await db.subscriptions_plans.find(query).sort("sort_order", 1).to_list(length=100)

    # Convert ObjectId to string
    for plan in plans:
        plan["id"] = str(plan.pop("_id"))

    active_count = await db.subscriptions_plans.count_documents({"status": PlanStatus.ACTIVE.value})

    return PlanListResponse(
        plans=[SubscriptionPlanResponse(**p) for p in plans],
        total=len(plans),
        active_count=active_count,
    )


@router.get("/plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def get_plan(
    plan_id: str,
    db=Depends(get_db),
):
    """Get a specific subscription plan."""
    try:
        plan = await db.subscriptions_plans.find_one({"_id": ObjectId(plan_id)})
    except:
        plan = await db.subscriptions_plans.find_one({"plan_type": plan_id})

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan["id"] = str(plan.pop("_id"))
    return SubscriptionPlanResponse(**plan)


@router.post("/plans", response_model=SubscriptionPlanResponse)
async def create_plan(
    plan: SubscriptionPlanCreate,
    db=Depends(get_db),
    _=Depends(RequirePermission("manage_plans")),
):
    """Create a new subscription plan."""
    existing = await db.subscriptions_plans.find_one({"plan_type": plan.plan_type.value})
    if existing:
        raise HTTPException(status_code=400, detail="Plan type already exists")

    if plan.is_default:
        await db.subscriptions_plans.update_many({}, {"$set": {"is_default": False}})

    plan_dict = plan.model_dump()
    plan_dict["status"] = plan_dict.get("status", PlanStatus.ACTIVE.value)
    plan_dict["created_at"] = datetime.utcnow()
    plan_dict["updated_at"] = datetime.utcnow()

    result = await db.subscriptions_plans.insert_one(plan_dict)
    plan_dict["id"] = str(result.inserted_id)
    plan_dict.pop("_id", None)

    logger.info(f"Created subscription plan: {plan.name}")
    return SubscriptionPlanResponse(**plan_dict)


@router.put("/plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def update_plan(
    plan_id: str,
    plan_update: SubscriptionPlanUpdate,
    db=Depends(get_db),
    _=Depends(RequirePermission("manage_plans")),
):
    """Update a subscription plan."""
    try:
        oid = ObjectId(plan_id)
        existing = await db.subscriptions_plans.find_one({"_id": oid})
    except:
        existing = await db.subscriptions_plans.find_one({"plan_type": plan_id})

    if not existing:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan_update.is_default:
        await db.subscriptions_plans.update_many(
            {"_id": {"$ne": existing["_id"]}},
            {"$set": {"is_default": False}}
        )

    update_dict = {k: v for k, v in plan_update.model_dump().items() if v is not None}
    update_dict["updated_at"] = datetime.utcnow()

    await db.subscriptions_plans.update_one({"_id": existing["_id"]}, {"$set": update_dict})

    updated = await db.subscriptions_plans.find_one({"_id": existing["_id"]})
    updated["id"] = str(updated.pop("_id"))

    logger.info(f"Updated subscription plan: {existing['name']}")
    return SubscriptionPlanResponse(**updated)


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    db=Depends(get_db),
    _=Depends(RequirePermission("manage_plans")),
):
    """Delete a subscription plan (mark as archived)."""
    try:
        oid = ObjectId(plan_id)
        plan = await db.subscriptions_plans.find_one({"_id": oid})
    except:
        plan = await db.subscriptions_plans.find_one({"plan_type": plan_id})

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.get("is_default"):
        raise HTTPException(status_code=400, detail="Cannot delete default plan")

    await db.subscriptions_plans.update_one(
        {"_id": plan["_id"]},
        {"$set": {"status": PlanStatus.ARCHIVED.value, "updated_at": datetime.utcnow()}}
    )

    logger.info(f"Archived subscription plan: {plan['name']}")
    return {"message": "Plan archived successfully"}


@router.post("/plans/init-defaults")
async def init_default_plans(
    db=Depends(get_db),
    _=Depends(RequirePermission("manage_plans")),
):
    """Initialize default subscription plans."""
    existing_count = await db.subscriptions_plans.count_documents({})
    if existing_count > 0:
        return {"message": f"Already have {existing_count} plans", "created": 0}

    default_plans = get_default_plans()
    now = datetime.utcnow()

    for plan in default_plans:
        plan_dict = plan.model_dump()
        plan_dict["status"] = PlanStatus.ACTIVE.value
        plan_dict["created_at"] = now
        plan_dict["updated_at"] = now
        await db.subscriptions_plans.insert_one(plan_dict)

    logger.info(f"Initialized {len(default_plans)} default subscription plans")
    return {"message": f"Created {len(default_plans)} default plans", "created": len(default_plans)}


@router.get("/user/{user_id}", response_model=UserSubscriptionInfo)
async def get_user_subscription(
    user_id: str,
    db=Depends(get_db),
):
    """Get subscription info for a specific user."""
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan_type = user.get("plan_type", PlanType.FREE.value)
    plan = await db.subscriptions_plans.find_one(
        {"plan_type": plan_type, "status": PlanStatus.ACTIVE.value}
    )

    if not plan:
        plan = await db.subscriptions_plans.find_one(
            {"plan_type": PlanType.FREE.value}
        )

    if not plan:
        raise HTTPException(status_code=500, detail="No active plan found")

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    today_start = datetime(now.year, now.month, now.day)

    audio_stats = await db.audio_files.aggregate([
        {"$match": {"user_id": ObjectId(user_id)}},
        {"$group": {
            "_id": None,
            "total_chars": {"$sum": {"$strLenCP": "$text_input"}},
            "total_audio": {"$sum": 1},
            "this_month_chars": {
                "$sum": {"$cond": [{"$gte": ["$created_at", month_start]}, {"$strLenCP": "$text_input"}, 0]}
            },
            "this_month_audio": {
                "$sum": {"$cond": [{"$gte": ["$created_at", month_start]}, 1, 0]}
            },
        }}
    ]).to_list(length=1)
    stats = audio_stats[0] if audio_stats else {}

    daily_audio = await db.audio_files.count_documents({
        "user_id": ObjectId(user_id),
        "created_at": {"$gte": today_start}
    })

    plan_limits = plan.get("limits", {})
    plan_features = plan.get("features", {})

    return UserSubscriptionInfo(
        user_id=user_id,
        plan_type=plan_type,
        plan_name=plan.get("name", "Unknown"),
        limits=PlanLimits(**plan_limits) if plan_limits else PlanLimits(),
        features=FeatureFlags(**plan_features) if plan_features else FeatureFlags(),
        usage={
            "chars_this_month": stats.get("this_month_chars", 0),
            "audio_this_month": stats.get("this_month_audio", 0),
            "audio_today": daily_audio,
        },
        quota_remaining={
            "chars_remaining": max(0, plan_limits.get("max_chars_per_month", 0) - stats.get("this_month_chars", 0)),
            "audio_remaining_today": max(0, plan_limits.get("max_audio_per_day", 0) - daily_audio),
        },
        is_trial=user.get("is_trial", False),
        trial_ends_at=user.get("trial_ends_at"),
    )
