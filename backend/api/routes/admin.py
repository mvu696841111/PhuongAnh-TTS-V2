"""
Admin API routes for PhuongAnh-TTS.
Handles user management, account management, and finance analytics.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Vietnam timezone
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


def get_db():
    """Get database instance."""
    return get_database()


async def get_current_admin_user(
    authorization: Optional[str] = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Dependency to verify admin access."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization[7:]
    
    from jose import jwt, JWTError
    settings = get_settings()
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        return user
        
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


class UserResponse(BaseModel):
    id: str
    email: str
    username: Optional[str]
    phone: Optional[str]
    role: str
    subscription_plan: str
    subscription_status: str
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime]


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    page_size: int


class FinanceStats(BaseModel):
    total_revenue: float
    active_subscriptions: int
    free_users: int
    paid_users: int
    revenue_by_plan: dict
    new_users_this_month: int
    churned_users_this_month: int


# ===========================================
# Check Admin Access
# ===========================================

@router.get("/check")
async def check_admin(
    current_user: dict = Depends(get_current_admin_user)
):
    """Verify if current user is admin."""
    return {
        "is_admin": True,
        "user_id": str(current_user["_id"]),
        "email": current_user["email"]
    }


@router.get("/dashboard", response_model=dict)
async def get_dashboard_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get dashboard statistics."""
    try:
        settings = get_settings()

        # User stats
        total_users = await db.users.count_documents({})
        verified_users = await db.users.count_documents({"is_verified": True})

        # Subscription stats - use unified plan names
        free_users = await db.users.count_documents({"subscription_plan": "free"})
        # CRITICAL FIX: Use plus/pro (not basic) for correct revenue calculation
        plus_users = await db.users.count_documents({"subscription_plan": "plus"})
        pro_users = await db.users.count_documents({"subscription_plan": "pro"})

        # This month (using Vietnam timezone)
        first_of_month = now_vietnam().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_month_utc = first_of_month.astimezone(timezone.utc)
        new_users_this_month = await db.users.count_documents({"created_at": {"$gte": first_of_month_utc}})

        # Active sessions
        active_sessions = await db.sessions.count_documents({
            "is_revoked": False,
            "expires_at": {"$gt": now_vietnam()}
        })

        # Usage logs this month
        usage_this_month = await db.usage_logs.count_documents({"timestamp": {"$gte": first_of_month_utc}})

        return {
            "total_users": total_users,
            "verified_users": verified_users,
            "free_users": free_users,
            "plus_users": plus_users,
            "pro_users": pro_users,
            "paid_users": plus_users + pro_users,
            "new_users_this_month": new_users_this_month,
            "active_sessions": active_sessions,
            "usage_this_month": usage_this_month,
        }
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users", response_model=UserListResponse)
async def get_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    plan: Optional[str] = None,
    verified: Optional[bool] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get paginated list of users."""
    try:
        query = {}
        
        if search:
            query["$or"] = [
                {"email": {"$regex": search, "$options": "i"}},
                {"username": {"$regex": search, "$options": "i"}},
            ]
        
        if plan:
            query["subscription_plan"] = plan
        
        if verified is not None:
            query["is_verified"] = verified
        
        skip = (page - 1) * page_size
        
        total = await db.users.count_documents(query)
        cursor = db.users.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        users = await cursor.to_list(length=page_size)
        
        return UserListResponse(
            users=[
                UserResponse(
                    id=str(u["_id"]),
                    email=u["email"],
                    username=u.get("username"),
                    phone=u.get("phone"),
                    role=u.get("role", "user"),
                    subscription_plan=u.get("subscription_plan", "free"),
                    subscription_status=u.get("subscription_status", "active"),
                    is_verified=u.get("is_verified", False),
                    created_at=u["created_at"] or datetime.utcnow(),
                    last_login=u.get("last_login"),
                )
                for u in users
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Get users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get detailed user information."""
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get usage logs
        usage_logs = await db.usage_logs.find(
            {"user_id": ObjectId(user_id)}
        ).sort("timestamp", -1).limit(50).to_list(length=50)
        
        return {
            "user": {
                "id": str(user["_id"]),
                "email": user["email"],
                "username": user.get("username"),
                "phone": user.get("phone"),
                "role": user.get("role", "user"),
                "subscription_plan": user.get("subscription_plan", "free"),
                "subscription_status": user.get("subscription_status", "active"),
                "is_verified": user.get("is_verified", False),
                "created_at": str(user.get("created_at", "")),
                "last_login": str(user.get("last_login", "")),
            },
            "usage_logs": [
                {
                    "action": log.get("action", ""),
                    "timestamp": str(log.get("timestamp", "")),
                    "metadata": log.get("metadata", {}),
                }
                for log in usage_logs
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    plan: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Update user subscription plan or status."""
    try:
        update_data = {"updated_at": now_vietnam()}

        if plan:
            update_data["subscription_plan"] = plan
        if status:
            update_data["subscription_status"] = status
        if role:
            update_data["role"] = role

        result = await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        return {"message": "User updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Delete a user and all related data."""
    try:
        # Prevent self-deletion
        if user_id == str(current_user["_id"]):
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        
        # Delete user
        result = await db.users.delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete related data
        await db.sessions.delete_many({"user_id": ObjectId(user_id)})
        await db.subscriptions.delete_many({"user_id": ObjectId(user_id)})
        await db.usage_logs.delete_many({"user_id": ObjectId(user_id)})
        
        return {"message": "User deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions")
async def get_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    plan: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get paginated list of subscriptions."""
    try:
        query = {}
        
        if plan:
            query["plan"] = plan
        if status:
            query["status"] = status
        
        skip = (page - 1) * page_size
        
        total = await db.subscriptions.count_documents(query)
        cursor = db.subscriptions.find(query).sort("started_at", -1).skip(skip).limit(page_size)
        subscriptions = await cursor.to_list(length=page_size)
        
        # Enrich with user info
        enriched = []
        for sub in subscriptions:
            user = await db.users.find_one({"_id": sub["user_id"]})
            enriched.append({
                "id": str(sub["_id"]),
                "user_email": user["email"] if user else "Unknown",
                "plan": sub.get("plan", "free"),
                "status": sub.get("status", "active"),
                "started_at": str(sub.get("started_at", "")),
                "expires_at": str(sub.get("expires_at", "")) if sub.get("expires_at") else None,
                "auto_renew": sub.get("auto_renew", False),
            })
        
        return {
            "subscriptions": enriched,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Get subscriptions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscriptions/{subscription_id}/approve")
async def approve_subscription(
    subscription_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Approve a subscription and update user plan with proper expiration handling.
    """
    try:
        sub = await db.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        user = await db.users.find_one({"_id": sub["user_id"]})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        now = now_vietnam()
        new_plan = sub.get("plan", "plus")

        # Check if user has existing active subscription to extend
        current_expires = user.get("subscription_expires_at")
        current_expires_vn = to_vietnam(current_expires) if current_expires else None

        # If current subscription is still valid, extend from current expiration
        if current_expires_vn and current_expires_vn > now:
            expires_at = current_expires_vn + timedelta(days=30)
        else:
            expires_at = now + timedelta(days=30)

        # Update subscription status
        await db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {
                "status": "active",
                "approved_at": now,
                "approved_by": str(current_user["_id"]),
                "expires_at": expires_at
            }}
        )

        # Update user plan
        await db.users.update_one(
            {"_id": sub["user_id"]},
            {"$set": {
                "subscription_plan": new_plan,
                "subscription_status": "active",
                "subscription_expires_at": expires_at,
                "updated_at": now
            }}
        )

        logger.info(f"✓ Subscription {subscription_id} approved - user {user['email']} upgraded to {new_plan}")

        return {"message": f"Subscription approved. User upgraded to {new_plan}", "expires_at": str(expires_at)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approve subscription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscriptions/{subscription_id}/reject")
async def reject_subscription(
    subscription_id: str,
    reason: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Reject a subscription request."""
    try:
        await db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {
                "status": "rejected",
                "rejected_at": now_vietnam(),
                "rejected_by": str(current_user["_id"]),
                "reject_reason": reason or "Không có lý do"
            }}
        )

        return {"message": "Subscription rejected"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reject subscription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/set-plan")
async def admin_set_user_plan(
    user_id: str,
    plan: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Admin directly set user subscription plan with proper expiration.
    """
    try:
        # CRITICAL FIX: Use unified plan names (free/plus/pro, not basic/enterprise)
        valid_plans = ["free", "plus", "pro"]
        if plan not in valid_plans:
            raise HTTPException(status_code=400, detail=f"Invalid plan. Must be one of: {valid_plans}")

        now = now_vietnam()
        expires_at = None
        if plan != "free":
            # Check current expiration to extend properly
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            current_expires = user.get("subscription_expires_at") if user else None
            current_expires_vn = to_vietnam(current_expires) if current_expires else None

            if current_expires_vn and current_expires_vn > now:
                expires_at = current_expires_vn + timedelta(days=30)
            else:
                expires_at = now + timedelta(days=30)

        result = await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "subscription_plan": plan,
                "subscription_status": "active",
                "subscription_expires_at": expires_at,
                "updated_at": now
            }}
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        # Log the action
        await db.usage_logs.insert_one({
            "user_id": ObjectId(user_id),
            "action": "admin_set_plan",
            "timestamp": now,
            "metadata": {
                "new_plan": plan,
                "admin_id": str(current_user["_id"]),
                "admin_email": current_user["email"]
            }
        })

        return {"message": f"User plan updated to {plan}", "expires_at": str(expires_at) if expires_at else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin set plan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finance/stats", response_model=FinanceStats)
async def get_finance_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Get finance statistics with CORRECT revenue calculation.
    
    CRITICAL: Revenue is calculated from ACTUAL payment records, not user counts.
    This fixes the bug where basic_users * 199000 was wrong.
    """
    try:
        now = now_vietnam()
        now_utc = now.astimezone(timezone.utc)
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_month_utc = first_of_month.astimezone(timezone.utc)

        # User counts by plan - use unified plan names
        free_users = await db.users.count_documents({"subscription_plan": "free"})
        plus_users = await db.users.count_documents({"subscription_plan": "plus"})
        pro_users = await db.users.count_documents({"subscription_plan": "pro"})

        # New users this month
        new_users_this_month = await db.users.count_documents(
            {"created_at": {"$gte": first_of_month_utc}}
        )

        # Active subscriptions - check expiration properly
        active_subscriptions = await db.subscriptions.count_documents({
            "status": "active",
            "expires_at": {"$gt": now_utc}
        })

        # CRITICAL FIX: Calculate revenue from ACTUAL completed payments
        # Not user_count * price (which is WRONG - duplicates users)
        # Get actual payment amounts from payment records

        pipeline_payments = [
            {
                "$match": {
                    "status": "completed",
                    "created_at": {"$gte": first_of_month_utc}
                }
            },
            {
                "$group": {
                    "_id": "$plan",
                    "total_amount": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            }
        ]
        payment_summary = await db.payments.aggregate(pipeline_payments).to_list(length=None)

        # Build revenue from actual payments
        revenue_by_plan = {"free": 0, "plus": 0, "pro": 0}
        for p in payment_summary:
            plan = p["_id"]
            if plan in revenue_by_plan:
                revenue_by_plan[plan] = p["total_amount"]

        total_revenue = sum(revenue_by_plan.values())

        # Count users who actually paid (from payment records)
        pipeline_paid_users = [
            {"$group": {"_id": "$user_id"}},
            {"$count": "total"}
        ]
        paid_user_count_result = await db.payments.aggregate(pipeline_paid_users).to_list(length=None)
        actual_paid_users = paid_user_count_result[0]["total"] if paid_user_count_result else 0

        return FinanceStats(
            total_revenue=total_revenue,
            active_subscriptions=active_subscriptions,
            free_users=free_users,
            paid_users=actual_paid_users,
            revenue_by_plan=revenue_by_plan,
            new_users_this_month=new_users_this_month,
            churned_users_this_month=0,
        )
    except Exception as e:
        logger.error(f"Finance stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finance/revenue")
async def get_revenue_history(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get revenue history by day."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)

        # Aggregate actual payment amounts by day
        pipeline = [
            {
                "$match": {
                    "status": "completed",
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                    },
                    "total_amount": {"$sum": "$amount"},
                    "count": {"$sum": 1},
                    "free": {"$sum": {"$cond": [{"$eq": ["$plan", "free"]}, 1, 0]}},
                    "paid": {"$sum": {"$cond": [{"$ne": ["$plan", "free"]}, 1, 0]}},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        history = await db.payments.aggregate(pipeline).to_list(length=days)

        return {"history": history, "days": days}
    except Exception as e:
        logger.error(f"Revenue history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Payment Management
# ===========================================

@router.get("/payments")
async def get_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get all payment orders."""
    try:
        query = {}
        if status:
            query["status"] = status

        skip = (page - 1) * page_size
        total = await db.payments.count_documents(query)
        cursor = db.payments.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        payments = await cursor.to_list(length=page_size)

        enriched = []
        for p in payments:
            user = await db.users.find_one({"_id": p["user_id"]})
            enriched.append({
                "id": str(p["_id"]),
                "order_id": p["order_id"],
                "user_email": user["email"] if user else "Unknown",
                "user_id": str(p["user_id"]),
                "plan": p.get("plan", "unknown"),
                "amount": p.get("amount", 0),
                "method": p.get("method", "unknown"),
                "status": p.get("status", "unknown"),
                "user_confirmed": p.get("user_confirmed", False),
                "created_at": str(p.get("created_at", "")),
                "paid_at": str(p.get("paid_at")) if p.get("paid_at") else None,
            })

        return {
            "payments": enriched,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Get payments error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/payments/{order_id}/approve")
async def approve_payment(
    order_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Approve payment and activate subscription with proper expiration."""
    try:
        from datetime import timedelta

        payment = await db.payments.find_one({"order_id": order_id})
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        user_id = payment["user_id"]
        new_plan = payment.get("plan", "plus")

        # Check if user has existing active subscription
        user = await db.users.find_one({"_id": user_id})
        current_expires = user.get("subscription_expires_at")
        current_expires_vn = to_vietnam(current_expires) if current_expires else None
        now = now_vietnam()

        # Calculate expiration - extend from current if still valid, otherwise start fresh
        if current_expires_vn and current_expires_vn > now:
            expires_at = current_expires_vn + timedelta(days=30)
        else:
            expires_at = now + timedelta(days=30)

        # Update payment status
        await db.payments.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "approved",
                "approved_at": now_vietnam(),
                "approved_by": str(current_user["_id"])
            }}
        )

        # Update subscription
        await db.subscriptions.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "active",
                "approved_at": now_vietnam(),
                "approved_by": str(current_user["_id"]),
                "expires_at": expires_at
            }}
        )

        # Update user plan WITH expiration
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {
                "subscription_plan": new_plan,
                "subscription_status": "active",
                "subscription_expires_at": expires_at,
                "subscription_started_at": current_expires_vn if current_expires_vn and current_expires_vn > now else now_vietnam(),
                "updated_at": now_vietnam()
            }}
        )

        logger.info(f"✓ Payment {order_id} approved - {user['email']} upgraded to {new_plan}, expires: {expires_at}")

        return {"message": f"Thanh toán đã được duyệt. User lên gói {new_plan}", "expires_at": str(expires_at)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approve payment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/payments/{order_id}/reject")
async def reject_payment(
    order_id: str,
    reason: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Reject payment."""
    try:
        await db.payments.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "rejected",
                "rejected_at": datetime.utcnow(),
                "rejected_by": str(current_user["_id"]),
                "reject_reason": reason or "Không có lý do"
            }}
        )

        # Update subscription
        await db.subscriptions.update_one(
            {"order_id": order_id},
            {"$set": {"status": "rejected"}}
        )

        return {"message": "Thanh toán đã bị từ chối"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reject payment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage/logs")
async def get_usage_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    days: int = Query(7, ge=1, le=90),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get usage logs with filters."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)

        query = {"timestamp": {"$gte": start_date_utc}}

        if user_id:
            query["user_id"] = ObjectId(user_id)

        if action:
            query["action"] = action

        skip = (page - 1) * page_size

        total = await db.usage_logs.count_documents(query)
        cursor = db.usage_logs.find(query).sort("timestamp", -1).skip(skip).limit(page_size)
        logs = await cursor.to_list(length=page_size)

        # Enrich with user email
        enriched_logs = []
        for log in logs:
            user = await db.users.find_one({"_id": log.get("user_id")})
            # Convert timestamp to Vietnam timezone for display
            timestamp_vn = to_vietnam(log.get("timestamp"))
            enriched_logs.append({
                "id": str(log["_id"]),
                "user_email": user["email"] if user else "Unknown",
                "action": log.get("action", ""),
                "timestamp": str(timestamp_vn) if timestamp_vn else "",
                "timestamp_vietnam": timestamp_vn.isoformat() if timestamp_vn else None,
                "metadata": log.get("metadata", {}),
            })

        return {
            "logs": enriched_logs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Usage logs error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Transaction & Revenue Tracking
# ===========================================

@router.get("/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    plan: Optional[str] = None,
    method: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get all payment transactions with pagination and filters."""
    try:
        query = {}
        
        if status:
            query["status"] = status
        if plan:
            query["plan"] = plan
        if method:
            query["method"] = method
        
        skip = (page - 1) * page_size
        total = await db.payments.count_documents(query)
        
        cursor = db.payments.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        transactions = await cursor.to_list(length=page_size)
        
        # Enrich with user info
        enriched = []
        for t in transactions:
            user = await db.users.find_one({"_id": t["user_id"]})
            enriched.append({
                "id": str(t["_id"]),
                "order_id": t["order_id"],
                "user_email": user["email"] if user else "Unknown",
                "user_id": str(t["user_id"]),
                "plan": t.get("plan", "unknown"),
                "method": t.get("method", "unknown"),
                "amount": t.get("amount", 0),
                "status": t.get("status", "unknown"),
                "created_at": str(t.get("created_at", "")),
                "created_at_vn": to_vietnam(t.get("created_at")).isoformat() if t.get("created_at") else None,
                "approved_at": str(t.get("approved_at", "")) if t.get("approved_at") else None,
                "approved_by": str(t.get("approved_by", "")) if t.get("approved_by") else None,
            })
        
        return {
            "transactions": enriched,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Get transactions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/summary")
async def get_revenue_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get revenue summary from actual payment records."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)
        
        # Total revenue in period
        pipeline_total = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1},
                    "avg_order": {"$avg": "$amount"}
                }
            }
        ]
        total_result = await db.payments.aggregate(pipeline_total).to_list(length=1)
        total_revenue = total_result[0]["total_revenue"] if total_result else 0
        total_orders = total_result[0]["count"] if total_result else 0
        
        # Revenue by plan
        pipeline_by_plan = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": "$plan",
                    "revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            }
        ]
        revenue_by_plan = await db.payments.aggregate(pipeline_by_plan).to_list(length=None)
        
        # Revenue by payment method
        pipeline_by_method = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": "$method",
                    "revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            }
        ]
        revenue_by_method = await db.payments.aggregate(pipeline_by_method).to_list(length=None)
        
        # Revenue by day
        pipeline_by_day = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                    },
                    "revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        revenue_by_day = await db.payments.aggregate(pipeline_by_day).to_list(length=days)
        
        # Fill missing days with zeros
        date_map = {r["_id"]: r for r in revenue_by_day}
        result_by_day = []
        current = start_date.date()
        end = now.date()
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            if date_str in date_map:
                result_by_day.append(date_map[date_str])
            else:
                result_by_day.append({"_id": date_str, "revenue": 0, "count": 0})
            current += timedelta(days=1)
        
        # Pending payments count
        pending_count = await db.payments.count_documents({"status": "pending"})
        
        return {
            "period_days": days,
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "avg_order_value": round(total_revenue / total_orders, 0) if total_orders > 0 else 0,
            "pending_count": pending_count,
            "revenue_by_plan": [
                {"plan": r["_id"], "revenue": r["revenue"], "count": r["count"]}
                for r in revenue_by_plan
            ],
            "revenue_by_method": [
                {"method": r["_id"], "revenue": r["revenue"], "count": r["count"]}
                for r in revenue_by_method
            ],
            "revenue_by_day": result_by_day,
        }
    except Exception as e:
        logger.error(f"Revenue summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/monthly")
async def get_monthly_revenue(
    months: int = Query(6, ge=1, le=24),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get monthly revenue for the past N months."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=months * 31)
        start_date_utc = start_date.astimezone(timezone.utc)
        
        pipeline = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": {
                        "year": {"$year": "$created_at"},
                        "month": {"$month": "$created_at"}
                    },
                    "revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id.year": 1, "_id.month": 1}}
        ]
        
        monthly = await db.payments.aggregate(pipeline).to_list(length=months)
        
        # Format response
        result = []
        for m in monthly:
            result.append({
                "year": m["_id"]["year"],
                "month": m["_id"]["month"],
                "month_name": datetime(m["_id"]["year"], m["_id"]["month"], 1).strftime("%B"),
                "revenue": m["revenue"],
                "count": m["count"]
            })
        
        return {"monthly": result}
    except Exception as e:
        logger.error(f"Monthly revenue error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/growth")
async def get_revenue_growth(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Calculate revenue growth metrics."""
    try:
        now = now_vietnam()
        
        # This month
        first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_this_month_utc = first_this_month.astimezone(timezone.utc)
        
        # Last month
        first_last_month = (first_this_month - timedelta(days=1)).replace(day=1)
        first_last_month_utc = first_last_month.astimezone(timezone.utc)
        
        # This month revenue
        this_month = await db.payments.aggregate([
            {"$match": {"status": {"$in": ["approved", "completed"]}, "created_at": {"$gte": first_this_month_utc}}},
            {"$group": {"_id": None, "revenue": {"$sum": "$amount"}, "count": {"$sum": 1}}}
        ]).to_list(length=1)
        
        # Last month revenue
        last_month = await db.payments.aggregate([
            {"$match": {
                "status": {"$in": ["approved", "completed"]},
                "created_at": {"$gte": first_last_month_utc, "$lt": first_this_month_utc}
            }},
            {"$group": {"_id": None, "revenue": {"$sum": "$amount"}, "count": {"$sum": 1}}}
        ]).to_list(length=1)
        
        this_revenue = this_month[0]["revenue"] if this_month else 0
        this_count = this_month[0]["count"] if this_month else 0
        last_revenue = last_month[0]["revenue"] if last_month else 0
        last_count = last_month[0]["count"] if last_month else 0
        
        # Calculate growth
        revenue_growth = 0
        if last_revenue > 0:
            revenue_growth = round(((this_revenue - last_revenue) / last_revenue) * 100, 1)
        
        count_growth = 0
        if last_count > 0:
            count_growth = round(((this_count - last_count) / last_count) * 100, 1)
        
        return {
            "this_month": {
                "revenue": this_revenue,
                "count": this_count
            },
            "last_month": {
                "revenue": last_revenue,
                "count": last_count
            },
            "growth": {
                "revenue_percent": revenue_growth,
                "count_percent": count_growth
            }
        }
    except Exception as e:
        logger.error(f"Revenue growth error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/quota")
async def get_user_quota(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get detailed quota and usage information for a specific user."""
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        settings = get_settings()
        now = now_vietnam()
        
        # Get user's plan
        plan = user.get("subscription_plan", "free")
        plan_status = user.get("subscription_status", "active")
        expires_at = user.get("subscription_expires_at")
        expires_at_vn = to_vietnam(expires_at) if expires_at else None
        
        # Calculate days remaining
        days_remaining = None
        if plan != "free" and expires_at_vn:
            if expires_at_vn > now:
                days_remaining = (expires_at_vn - now).days
            else:
                days_remaining = 0  # Expired
        
        # Define limits based on plan
        if plan == "free":
            limits = {
                "daily_audio_limit": settings.FREE_DAILY_AUDIO_LIMIT,
                "monthly_chars_limit": settings.FREE_MONTHLY_CHARS_LIMIT,
                "max_text_length": settings.FREE_MAX_TEXT_LENGTH,
                "max_duration": settings.FREE_MAX_DURATION,
            }
        elif plan == "plus":
            limits = {
                "daily_audio_limit": settings.PLUS_DAILY_AUDIO_LIMIT,
                "monthly_chars_limit": settings.PLUS_MONTHLY_CHARS_LIMIT,
                "max_text_length": settings.PLUS_MAX_TEXT_LENGTH,
                "max_duration": settings.PLUS_MAX_DURATION,
            }
        else:  # pro
            limits = {
                "daily_audio_limit": settings.PRO_DAILY_AUDIO_LIMIT,
                "monthly_chars_limit": settings.PRO_MONTHLY_CHARS_LIMIT,
                "max_text_length": settings.PRO_MAX_TEXT_LENGTH,
                "max_duration": settings.PRO_MAX_DURATION,
            }
        
        # Get today's usage
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start.astimezone(timezone.utc)
        
        daily_usage = await db.usage_logs.count_documents({
            "user_id": ObjectId(user_id),
            "timestamp": {"$gte": today_start_utc},
            "action": {"$in": ["tts", "generate", "synthesize"]}
        })
        
        # Get this month's usage
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_month_utc = first_of_month.astimezone(timezone.utc)
        
        # Aggregate monthly usage
        pipeline_monthly = [
            {
                "$match": {
                    "user_id": ObjectId(user_id),
                    "timestamp": {"$gte": first_of_month_utc},
                    "action": {"$in": ["tts", "generate", "synthesize"]}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_calls": {"$sum": 1},
                    "total_chars": {"$sum": {"$ifNull": ["$metadata.char_count", 0]}},
                    "total_duration": {"$sum": {"$ifNull": ["$metadata.duration", 0]}}
                }
            }
        ]
        monthly_result = await db.usage_logs.aggregate(pipeline_monthly).to_list(length=1)
        monthly_usage = monthly_result[0] if monthly_result else {"total_calls": 0, "total_chars": 0, "total_duration": 0}
        
        # Calculate remaining
        daily_remaining = max(0, limits["daily_audio_limit"] - daily_usage) if limits["daily_audio_limit"] > 0 else -1
        monthly_remaining = max(0, limits["monthly_chars_limit"] - monthly_usage["total_chars"]) if limits["monthly_chars_limit"] > 0 else -1
        
        # Usage percentage
        daily_percent = min(100, (daily_usage / limits["daily_audio_limit"] * 100)) if limits["daily_audio_limit"] > 0 else 0
        monthly_percent = min(100, (monthly_usage["total_chars"] / limits["monthly_chars_limit"] * 100)) if limits["monthly_chars_limit"] > 0 else 0
        
        return {
            "user_id": user_id,
            "email": user["email"],
            "plan": plan,
            "plan_status": plan_status,
            "subscription_expires_at": str(expires_at_vn) if expires_at_vn else None,
            "days_remaining": days_remaining,
            "limits": limits,
            "usage": {
                "daily": {
                    "used": daily_usage,
                    "limit": limits["daily_audio_limit"],
                    "remaining": daily_remaining,
                    "percent": round(daily_percent, 1)
                },
                "monthly": {
                    "used": monthly_usage["total_calls"],
                    "chars_used": monthly_usage["total_chars"],
                    "chars_limit": limits["monthly_chars_limit"],
                    "chars_remaining": monthly_remaining,
                    "duration_used": monthly_usage["total_duration"],
                    "percent": round(monthly_percent, 1)
                }
            },
            "is_expired": days_remaining == 0 if days_remaining is not None else False,
            "can_use": plan == "free" or (days_remaining is not None and days_remaining > 0)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user quota error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Analytics Endpoints
# ===========================================

@router.get("/analytics/users-by-date")
async def get_users_by_date(
    days: int = Query(30, ge=7, le=90),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get user registrations by date for chart."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)

        pipeline = [
            {
                "$match": {
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                    },
                    "count": {"$sum": 1},
                    "free": {"$sum": {"$cond": [{"$eq": ["$subscription_plan", "free"]}, 1, 0]}},
                    "paid": {"$sum": {"$cond": [{"$ne": ["$subscription_plan", "free"]}, 1, 0]}},
                }
            },
            {"$sort": {"_id": 1}}
        ]

        history = await db.users.aggregate(pipeline).to_list(length=days)

        # Fill missing dates with zeros
        date_map = {h["_id"]: h for h in history}
        result = []
        current = start_date.date()
        end = now.date()
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            if date_str in date_map:
                result.append(date_map[date_str])
            else:
                result.append({"_id": date_str, "count": 0, "free": 0, "paid": 0})
            current += timedelta(days=1)

        return {"history": result, "days": days}
    except Exception as e:
        logger.error(f"Users by date error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/usage-stats")
async def get_usage_stats(
    days: int = Query(30, ge=7, le=90),
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get TTS usage statistics by date."""
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)

        pipeline = [
            {
                "$match": {
                    "timestamp": {"$gte": start_date_utc},
                    "action": {"$in": ["tts", "generate", "synthesize"]}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}
                    },
                    "total_calls": {"$sum": 1},
                    "total_chars": {"$sum": {"$ifNull": ["$metadata.char_count", 0]}},
                    "total_duration": {"$sum": {"$ifNull": ["$metadata.duration", 0]}},
                }
            },
            {"$sort": {"_id": 1}}
        ]

        history = await db.usage_logs.aggregate(pipeline).to_list(length=days)

        # Fill missing dates
        date_map = {h["_id"]: h for h in history}
        result = []
        current = start_date.date()
        end = now.date()
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            if date_str in date_map:
                result.append(date_map[date_str])
            else:
                result.append({"_id": date_str, "total_calls": 0, "total_chars": 0, "total_duration": 0})
            current += timedelta(days=1)

        # Summary stats
        total_calls = sum(h["total_calls"] for h in result)
        total_chars = sum(h["total_chars"] for h in result)
        total_duration = sum(h["total_duration"] for h in result)

        return {
            "history": result,
            "days": days,
            "summary": {
                "total_calls": total_calls,
                "total_chars": total_chars,
                "total_duration_seconds": total_duration,
                "avg_calls_per_day": round(total_calls / days, 1) if days > 0 else 0,
            }
        }
    except Exception as e:
        logger.error(f"Usage stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/metrics")
async def get_analytics_metrics(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get ARPU, churn rate and other metrics."""
    try:
        now = now_vietnam()
        now_utc = now.astimezone(timezone.utc)
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_month_utc = first_of_month.astimezone(timezone.utc)

        # User counts
        total_users = await db.users.count_documents({})
        free_users = await db.users.count_documents({"subscription_plan": "free"})
        paid_users = await db.users.count_documents({"subscription_plan": {"$ne": "free"}})

        # Monthly revenue
        pipeline_revenue = [
            {
                "$match": {
                    "status": "completed",
                    "created_at": {"$gte": first_of_month_utc}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$amount"}
                }
            }
        ]
        revenue_result = await db.payments.aggregate(pipeline_revenue).to_list(length=1)
        monthly_revenue = revenue_result[0]["total"] if revenue_result else 0

        # ARPU (Average Revenue Per User) - Monthly revenue / paid users
        arpu = round(monthly_revenue / paid_users, 2) if paid_users > 0 else 0

        # ARPU per paid user (ARPPU)
        arppu = round(monthly_revenue / paid_users, 2) if paid_users > 0 else 0

        # MRR (Monthly Recurring Revenue) - from active subscriptions
        active_subscriptions = await db.subscriptions.count_documents({
            "status": "active",
            "expires_at": {"$gt": now_utc}
        })

        # Calculate plan distribution for revenue breakdown
        plus_users = await db.users.count_documents({"subscription_plan": "plus"})
        pro_users = await db.users.count_documents({"subscription_plan": "pro"})

        # Revenue by plan this month
        revenue_by_plan = {"free": 0, "plus": 0, "pro": 0}
        pipeline_by_plan = [
            {
                "$match": {
                    "status": "completed",
                    "created_at": {"$gte": first_of_month_utc}
                }
            },
            {
                "$group": {
                    "_id": "$plan",
                    "total": {"$sum": "$amount"}
                }
            }
        ]
        plan_revenue = await db.payments.aggregate(pipeline_by_plan).to_list(length=None)
        for p in plan_revenue:
            if p["_id"] in revenue_by_plan:
                revenue_by_plan[p["_id"]] = p["total"]

        # Churn calculation (users who expired this month)
        churned_this_month = await db.users.count_documents({
            "subscription_status": "expired",
            "subscription_expires_at": {
                "$gte": first_of_month_utc,
                "$lte": now_utc
            }
        })

        # Previous month paid users for churn rate
        prev_month_start = (first_of_month - timedelta(days=1)).replace(day=1)
        prev_month_start_utc = prev_month_start.astimezone(timezone.utc)

        # New paid users this month
        new_paid_this_month = await db.users.count_documents({
            "created_at": {"$gte": first_of_month_utc},
            "subscription_plan": {"$ne": "free"}
        })

        # Churn rate = churned / (previous_paid + new_paid) * 100
        prev_paid = paid_users - new_paid_this_month + churned_this_month
        churn_rate = round((churned_this_month / prev_paid * 100), 1) if prev_paid > 0 else 0

        return {
            "arpu": arpu,
            "arppu": arppu,
            "mrr": monthly_revenue,
            "arr": monthly_revenue * 12,
            "churn_rate": churn_rate,
            "churned_this_month": churned_this_month,
            "active_subscriptions": active_subscriptions,
            "revenue_by_plan": revenue_by_plan,
            "plan_breakdown": {
                "free": free_users,
                "plus": plus_users,
                "pro": pro_users
            },
            "conversion_rate": round((paid_users / total_users * 100), 1) if total_users > 0 else 0
        }
    except Exception as e:
        logger.error(f"Analytics metrics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Audio History Management
# ===========================================

@router.get("/audio/history", response_model=dict)
async def get_audio_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[str] = None,
    voice_id: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get audio history/recordings with pagination and filtering."""
    try:
        # Build query
        query = {}
        if user_id:
            query["user_id"] = ObjectId(user_id)
        if voice_id:
            query["voice_id"] = voice_id
        
        # Get total count
        total = await db.audio_files.count_documents(query)
        
        # Get paginated results
        skip = (page - 1) * page_size
        cursor = db.audio_files.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        
        audios = []
        async for audio in cursor:
            # Get user info
            user = await db.users.find_one({"_id": audio["user_id"]})
            audio["_id"] = str(audio["_id"])
            audio["user_id"] = str(audio["user_id"])
            audio["user_email"] = user.get("email", "Unknown") if user else "Unknown"
            audio["user_name"] = user.get("name", "") if user else ""
            audios.append(audio)
        
        pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        
        return {
            "items": audios,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages
        }
    except Exception as e:
        logger.error(f"Audio history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audio/stats", response_model=dict)
async def get_audio_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Get audio generation statistics."""
    try:
        # Total audios
        total_audios = await db.audio_files.count_documents({})
        
        # Total size
        pipeline_size = [
            {"$group": {"_id": None, "total_size": {"$sum": "$filesize"}}}
        ]
        size_result = await db.audio_files.aggregate(pipeline_size).to_list(length=1)
        total_size = size_result[0]["total_size"] if size_result else 0
        
        # Audios today
        today_start = now_vietnam().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start.astimezone(timezone.utc)
        audios_today = await db.audio_files.count_documents({
            "created_at": {"$gte": today_start_utc}
        })
        
        # Total duration
        pipeline_duration = [
            {"$group": {"_id": None, "total_duration": {"$sum": "$duration"}}}
        ]
        duration_result = await db.audio_files.aggregate(pipeline_duration).to_list(length=1)
        total_duration = duration_result[0]["total_duration"] if duration_result else 0
        
        # Audios by voice
        pipeline_voice = [
            {"$group": {"_id": "$voice_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        voice_stats = await db.audio_files.aggregate(pipeline_voice).to_list(length=10)
        
        # Audios by user (top 10)
        pipeline_user = [
            {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        user_stats = await db.audio_files.aggregate(pipeline_user).to_list(length=10)
        
        # Enrich user stats with email
        enriched_user_stats = []
        for stat in user_stats:
            user = await db.users.find_one({"_id": stat["_id"]})
            enriched_user_stats.append({
                "user_id": str(stat["_id"]),
                "email": user.get("email", "Unknown") if user else "Unknown",
                "count": stat["count"]
            })
        
        # Daily audio counts (last 30 days)
        thirty_days_ago = now_vietnam() - timedelta(days=30)
        thirty_days_ago_utc = thirty_days_ago.astimezone(timezone.utc)
        pipeline_daily = [
            {"$match": {"created_at": {"$gte": thirty_days_ago_utc}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ]
        daily_stats = await db.audio_files.aggregate(pipeline_daily).to_list(length=30)
        
        return {
            "total_audios": total_audios,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "total_duration_seconds": round(total_duration, 1),
            "total_duration_hours": round(total_duration / 3600, 2),
            "audios_today": audios_today,
            "by_voice": [{"voice_id": v["_id"] or "unknown", "count": v["count"]} for v in voice_stats],
            "top_users": enriched_user_stats,
            "daily_stats": [{"date": d["_id"], "count": d["count"]} for d in daily_stats]
        }
    except Exception as e:
        logger.error(f"Audio stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
