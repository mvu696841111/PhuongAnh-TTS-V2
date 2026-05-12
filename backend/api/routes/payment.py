"""
Payment API routes for PhuongAnh-TTS Backend.
Handles payment processing and order management.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from core.database import get_database
from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])

# Bank accounts for manual payment
BANK_ACCOUNTS = {
    "vietcombank": {
        "bank": "Vietcombank",
        "account": "1234567890",
        "name": "CONG TY PHUONGANH TTS"
    },
    "techcombank": {
        "bank": "Techcombank",
        "account": "0987654321",
        "name": "CONG TY PHUONGANH TTS"
    }
}

PLAN_PRICES = {
    "free": 0,
    "basic": 199000,
    "pro": 499000,
    "enterprise": 0,
}


class CreatePaymentRequest(BaseModel):
    plan: str
    method: str = "vnpay"


class PaymentResponse(BaseModel):
    order_id: str
    status: str
    amount: int
    plan: str
    method: str
    payment_info: Optional[dict] = None
    created_at: datetime


def get_db():
    return get_database()


def get_current_user_id(token: str) -> Optional[str]:
    """Get user ID from token."""
    from jose import jwt, JWTError
    from core.config import get_settings
    settings = get_settings()

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


@router.post("/create", response_model=PaymentResponse)
async def create_payment(
    request: CreatePaymentRequest,
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Create a new payment order.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization[7:]
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Validate plan
    if request.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="Invalid plan")

    amount = PLAN_PRICES[request.plan]
    if amount == 0 and request.plan != "enterprise":
        raise HTTPException(status_code=400, detail="Cannot pay for this plan")

    # Get user
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already has pending payment
    existing = await db.payments.find_one({
        "user_id": ObjectId(user_id),
        "status": "pending"
    })
    if existing:
        raise HTTPException(status_code=400, detail="Bạn đã có đơn hàng đang chờ xử lý")

    # Create order
    order_id = f"PA{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    payment_info = None
    if request.method == "banking":
        payment_info = BANK_ACCOUNTS["vietcombank"]
    elif request.method == "cash":
        payment_info = {"message": "Vui lòng đến văn phòng công ty để thanh toán tiền mặt"}

    payment_doc = {
        "order_id": order_id,
        "user_id": ObjectId(user_id),
        "plan": request.plan,
        "method": request.method,
        "amount": amount,
        "status": "pending",
        "payment_info": payment_info,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    await db.payments.insert_one(payment_doc)

    # Also create subscription request
    subscription_doc = {
        "user_id": ObjectId(user_id),
        "plan": request.plan,
        "order_id": order_id,
        "status": "pending_payment",
        "requested_at": datetime.utcnow(),
        "billing_cycle": "monthly",
        "price": amount,
    }
    await db.subscriptions.insert_one(subscription_doc)

    logger.info(f"✓ Created payment order: {order_id} for user {user['email']}, plan {request.plan}")

    return PaymentResponse(
        order_id=order_id,
        status="pending",
        amount=amount,
        plan=request.plan,
        method=request.method,
        payment_info=payment_info,
        created_at=datetime.utcnow()
    )


@router.post("/callback")
async def payment_callback(
    order_id: str = Query(None),
    status: str = Query("success"),
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Payment gateway callback.
    In production, this would be called by VNPay/MoMo after payment.
    """
    # Accept JSON body as alternative to query params
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization[7:]
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Find payment
    payment = await db.payments.find_one({"order_id": order_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Order not found")

    # Verify ownership
    if str(payment["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update payment status
    new_status = "completed" if status == "success" else "failed"
    await db.payments.update_one(
        {"order_id": order_id},
        {"$set": {
            "status": new_status,
            "paid_at": datetime.utcnow() if new_status == "completed" else None,
            "updated_at": datetime.utcnow()
        }}
    )

    if new_status == "completed":
        # Update subscription to awaiting approval
        await db.subscriptions.update_one(
            {"order_id": order_id},
            {"$set": {"status": "awaiting_approval"}}
        )

        logger.info(f"✓ Payment completed: {order_id}")

    return {"message": "OK", "status": new_status}


@router.get("/confirm")
async def confirm_payment(
    order_id: str,
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    User confirms they have completed payment (for banking/cash).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization[7:]
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    payment = await db.payments.find_one({"order_id": order_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Order not found")

    if str(payment["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.payments.update_one(
        {"order_id": order_id},
        {"$set": {
            "user_confirmed": True,
            "confirmed_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )

    logger.info(f"✓ User confirmed payment: {order_id}")

    return {"message": "Đã xác nhận. Admin sẽ kiểm tra và kích hoạt trong 24h."}


@router.get("/orders")
async def get_my_orders(
    authorization: str = Header(None),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Get user's payment orders."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization[7:]
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    payments = await db.payments.find(
        {"user_id": ObjectId(user_id)}
    ).sort("created_at", -1).limit(20).to_list(length=20)

    return {
        "orders": [
            {
                "order_id": p["order_id"],
                "plan": p["plan"],
                "amount": p["amount"],
                "method": p["method"],
                "status": p["status"],
                "created_at": str(p["created_at"]),
                "paid_at": str(p["paid_at"]) if p.get("paid_at") else None,
            }
            for p in payments
        ]
    }


@router.get("/bank-accounts")
async def get_bank_accounts():
    """Get bank account information for payment."""
    return {"accounts": BANK_ACCOUNTS}
