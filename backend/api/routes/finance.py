"""
Public Finance API routes.
Provides public access to revenue summaries for the finance page.
"""

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["Finance"])

VIETNAM_TZ = timezone(timedelta(hours=7))


def now_vietnam() -> datetime:
    return datetime.now(VIETNAM_TZ)


def to_vietnam(dt: datetime):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
    return dt.astimezone(VIETNAM_TZ)


@router.get("/summary")
async def get_finance_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Get public finance summary for display.
    No authentication required - shows aggregate data only.
    """
    try:
        now = now_vietnam()
        start_date = now - timedelta(days=days)
        start_date_utc = start_date.astimezone(timezone.utc)

        # Total revenue
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
                    "count": {"$sum":  1}
                }
            }
        ]
        total_result = await db.payments.aggregate(pipeline_total).to_list(length=1)
        total_revenue = total_result[0]["total_revenue"] if total_result else 0
        total_orders = total_result[0]["count"] if total_result else 0

        # Pending count
        pending_count = await db.payments.count_documents({"status": "pending"})

        # By plan
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
        by_plan = await db.payments.aggregate(pipeline_by_plan).to_list(length=None)

        # By day
        pipeline_by_day = [
            {
                "$match": {
                    "status": {"$in": ["approved", "completed"]},
                    "created_at": {"$gte": start_date_utc}
                }
            },
            {
                "$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "revenue": {"$sum": "$amount"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        by_day = await db.payments.aggregate(pipeline_by_day).to_list(length=days)

        # Fill missing days
        date_map = {r["_id"]: r for r in by_day}
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

        return {
            "period_days": days,
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "pending_count": pending_count,
            "revenue_by_plan": [
                {"plan": r["_id"], "revenue": r["revenue"], "count": r["count"]}
                for r in by_plan
            ],
            "revenue_by_day": result_by_day,
        }
    except Exception as e:
        logger.error(f"Finance summary error: {e}")
        return {
            "period_days": days,
            "total_revenue": 0,
            "total_orders": 0,
            "pending_count": 0,
            "revenue_by_plan": [],
            "revenue_by_day": []
        }


@router.get("/transactions")
async def get_finance_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Get recent transactions for display.
    No authentication required - hides sensitive info.
    """
    try:
        skip = (page - 1) * page_size
        total = await db.payments.count_documents({})

        cursor = db.payments.find({}).sort("created_at", -1).skip(skip).limit(page_size)
        transactions = await cursor.to_list(length=page_size)

        enriched = []
        for t in transactions:
            user = await db.users.find_one({"_id": t["user_id"]})
            enriched.append({
                "order_id": t["order_id"],
                "user_email": user["email"] if user else "Unknown",
                "plan": t.get("plan", "unknown"),
                "amount": t.get("amount", 0),
                "method": t.get("method", "unknown"),
                "status": t.get("status", "unknown"),
                "created_at_vn": to_vietnam(t.get("created_at")).isoformat() if t.get("created_at") else None,
            })

        return {
            "transactions": enriched,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"Finance transactions error: {e}")
        return {
            "transactions": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
        }
