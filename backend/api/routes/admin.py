"""
Admin API routes for PhuongAnh-TTS.
Handles user management, account management, and finance analytics.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from core.config import get_settings
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
        
        # Subscription stats
        free_users = await db.users.count_documents({"subscription_plan": "free"})
        paid_users = await db.users.count_documents({"subscription_plan": {"$in": ["basic", "pro", "enterprise"]}})
        
        # This month
        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_users_this_month = await db.users.count_documents({"created_at": {"$gte": first_of_month}})
        
        # Active sessions
        active_sessions = await db.sessions.count_documents({
            "is_revoked": False,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        # Usage logs this month
        usage_this_month = await db.usage_logs.count_documents({"timestamp": {"$gte": first_of_month}})
        
        return {
            "total_users": total_users,
            "verified_users": verified_users,
            "free_users": free_users,
            "paid_users": paid_users,
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
        update_data = {"updated_at": datetime.utcnow()}
        
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
    """Approve a subscription and update user plan."""
    try:
        from datetime import timedelta

        sub = await db.subscriptions.find_one({"_id": ObjectId(subscription_id)})
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        user = await db.users.find_one({"_id": sub["user_id"]})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        new_plan = sub.get("plan", "basic")
        expires_at = datetime.utcnow() + timedelta(days=30)

        # Update subscription status
        await db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {
                "status": "active",
                "approved_at": datetime.utcnow(),
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
                "updated_at": datetime.utcnow()
            }}
        )

        logger.info(f"✓ Subscription {subscription_id} approved - user {user['email']} upgraded to {new_plan}")

        return {"message": f"Subscription approved. User upgraded to {new_plan}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approve subscription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscriptions/{subscription_id}/reject")
async def reject_subscription(
    subscription_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: dict = Depends(get_current_admin_user)
):
    """Reject a subscription request."""
    try:
        await db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": {
                "status": "rejected",
                "rejected_at": datetime.utcnow(),
                "rejected_by": str(current_user["_id"])
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
    """Admin directly set user subscription plan."""
    try:
        from datetime import timedelta

        valid_plans = ["free", "basic", "pro", "enterprise"]
        if plan not in valid_plans:
            raise HTTPException(status_code=400, detail=f"Invalid plan. Must be one of: {valid_plans}")

        expires_at = None
        if plan != "free":
            expires_at = datetime.utcnow() + timedelta(days=30)

        result = await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "subscription_plan": plan,
                "subscription_status": "active",
                "updated_at": datetime.utcnow()
            }}
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="User not found")

        # Log the action
        await db.usage_logs.insert_one({
            "user_id": ObjectId(user_id),
            "action": "admin_set_plan",
            "timestamp": datetime.utcnow(),
            "metadata": {
                "new_plan": plan,
                "admin_id": str(current_user["_id"]),
                "admin_email": current_user["email"]
            }
        })

        return {"message": f"User plan updated to {plan}"}
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
    """Get finance statistics."""
    try:
        now = datetime.utcnow()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # User counts by plan
        free_users = await db.users.count_documents({"subscription_plan": "free"})
        basic_users = await db.users.count_documents({"subscription_plan": "basic"})
        pro_users = await db.users.count_documents({"subscription_plan": "pro"})
        enterprise_users = await db.users.count_documents({"subscription_plan": "enterprise"})
        
        # New users this month
        new_users_this_month = await db.users.count_documents(
            {"created_at": {"$gte": first_of_month}}
        )
        
        # Active subscriptions
        active_subscriptions = await db.subscriptions.count_documents(
            {"status": "active", "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}
        )
        
        # Calculate mock revenue
        revenue = {
            "basic": basic_users * 199000,
            "pro": pro_users * 499000,
            "enterprise": enterprise_users * 0,  # Custom pricing
        }
        
        return FinanceStats(
            total_revenue=sum(revenue.values()),
            active_subscriptions=active_subscriptions,
            free_users=free_users,
            paid_users=basic_users + pro_users + enterprise_users,
            revenue_by_plan=revenue,
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
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)
        
        # Aggregate user registrations by day
        pipeline = [
            {"$match": {"created_at": {"$gte": start_date}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "count": {"$sum": 1},
                "free": {"$sum": {"$cond": [{"$eq": ["$subscription_plan", "free"]}, 1, 0]}},
                "paid": {"$sum": {"$cond": [{"$ne": ["$subscription_plan", "free"]}, 1, 0]}},
            }},
            {"$sort": {"_id": 1}},
        ]
        
        history = await db.users.aggregate(pipeline).to_list(length=days)
        
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
    """Approve payment and activate subscription."""
    try:
        from datetime import timedelta

        payment = await db.payments.find_one({"order_id": order_id})
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        user_id = payment["user_id"]
        new_plan = payment.get("plan", "basic")

        # Update payment status
        await db.payments.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "approved",
                "approved_at": datetime.utcnow(),
                "approved_by": str(current_user["_id"])
            }}
        )

        # Update subscription
        await db.subscriptions.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "active",
                "approved_at": datetime.utcnow(),
                "approved_by": str(current_user["_id"]),
                "expires_at": datetime.utcnow() + timedelta(days=30)
            }}
        )

        # Update user plan
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {
                "subscription_plan": new_plan,
                "subscription_status": "active",
                "updated_at": datetime.utcnow()
            }}
        )

        user = await db.users.find_one({"_id": user_id})
        logger.info(f"✓ Payment {order_id} approved - {user['email']} upgraded to {new_plan}")

        return {"message": f"Thanh toán đã được duyệt. User lên gói {new_plan}"}
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
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)
        
        query = {"timestamp": {"$gte": start_date}}
        
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
            enriched_logs.append({
                "id": str(log["_id"]),
                "user_email": user["email"] if user else "Unknown",
                "action": log.get("action", ""),
                "timestamp": str(log.get("timestamp", "")),
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
