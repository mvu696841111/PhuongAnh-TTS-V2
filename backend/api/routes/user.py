"""
User routes for PhuongAnh-TTS Backend.
Handles user profile and usage management.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from models.schemas.user import (
    UserResponse,
    UserProfile,
    UserUpdate,
    UsageStats,
    DailyUsageItem,
)
from api.dependencies import (
    get_db,
    get_current_user,
    get_user_service,
    get_subscription_service,
    get_audio_service,
)
from services.user_service import UserService
from services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["User"])


# ===========================================
# Profile
# ===========================================

@router.get(
    "/profile",
    response_model=UserProfile,
    summary="Get current user profile",
    description="Get authenticated user's profile with usage statistics."
)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """
    Get current user's profile.
    """
    profile = await user_service.get_profile(str(current_user["_id"]))
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return profile


@router.put(
    "/profile",
    response_model=UserProfile,
    summary="Update user profile",
    description="Update authenticated user's profile information."
)
async def update_profile(
    data: UserUpdate,
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """
    Update user profile.
    
    - **username**: New username (optional)
    - **phone**: New phone number (optional)
    """
    profile = await user_service.update_profile(
        user_id=str(current_user["_id"]),
        username=data.username,
        phone=data.phone
    )
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update profile"
        )
    
    logger.info(f"Profile updated for user {current_user['email']}")
    
    return profile


# ===========================================
# Usage Statistics
# ===========================================

@router.get(
    "/usage",
    response_model=UsageStats,
    summary="Get usage statistics",
    description="Get current user's usage statistics and limits."
)
async def get_usage_stats(
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """
    Get user's usage statistics.
    
    Returns:
    - **daily_audio_count**: Number of audio generated today
    - **daily_audio_limit**: Maximum audio per day
    - **daily_audio_remaining**: Remaining audio for today
    - **monthly_characters**: Characters used this month
    - **monthly_chars_limit**: Maximum characters per month
    - **monthly_chars_remaining**: Remaining characters this month
    """
    stats = await user_service.get_usage_stats(str(current_user["_id"]))
    return stats


@router.get(
    "/usage/history",
    response_model=List[DailyUsageItem],
    summary="Get usage history",
    description="Get daily usage history for the past N days."
)
async def get_usage_history(
    days: int = Query(7, ge=1, le=30, description="Number of days to retrieve"),
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """
    Get daily usage history.
    
    - **days**: Number of days to retrieve (1-30, default 7)
    """
    history = await user_service.get_daily_usage_history(
        str(current_user["_id"]),
        days=days
    )
    
    return [
        DailyUsageItem(
            date=item["date"],
            audio_count=item["audio_count"],
            characters_used=item["characters_used"]
        )
        for item in history
    ]


# ===========================================
# Subscription
# ===========================================

@router.get(
    "/subscription",
    summary="Get subscription info",
    description="Get current user's subscription information."
)
async def get_subscription(
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Get current user's subscription.
    """
    subscription = await subscription_service.get_user_subscription(
        str(current_user["_id"])
    )
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    return subscription


@router.get(
    "/subscription/plans",
    summary="Get available plans",
    description="Get all available subscription plans."
)
async def get_available_plans(
    subscription_service: SubscriptionService = Depends(get_subscription_service)
):
    """
    Get list of available subscription plans.
    """
    plans = await subscription_service.get_available_plans()
    return {"plans": plans}


# ===========================================
# Account Management
# ===========================================

@router.delete(
    "/account",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user account",
    description="Permanently delete user account and all data."
)
async def delete_account(
    current_user: dict = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """
    Delete user account and all associated data.
    """
    success = await user_service.delete_user(str(current_user["_id"]))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to delete account"
        )
    
    logger.info(f"Account deleted for user {current_user['email']}")
    
    return None
