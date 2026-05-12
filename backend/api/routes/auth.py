"""
Authentication routes for PhuongAnh-TTS Backend.
Handles user registration, login, logout, and token management.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from models.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    PasswordChange,
    PasswordResetRequest,
    PasswordResetConfirm,
    UsageStats,
    DailyUsageItem,
)
from services.auth_service import AuthService
from services.user_service import UserService
from api.dependencies import (
    get_db,
    get_current_user,
    get_current_user_optional,
    get_auth_service,
    get_user_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ===========================================
# Registration
# ===========================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email and password."
)
async def register(
    user_data: UserCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Register a new user account.
    
    - **email**: Valid email address (required)
    - **password**: Password (min 8 characters, must contain uppercase, lowercase, and digit)
    - **username**: Optional username
    """
    # Check if email already exists
    existing = await db.users.find_one({"email": user_data.email.lower()})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Register user
    user, error = await auth_service.register_user(
        email=user_data.email,
        password=user_data.password,
        username=user_data.username
    )
    
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    logger.info(f"New user registered: {user_data.email}")
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user.get("username"),
        subscription_plan=user["subscription_plan"],
        is_verified=False
    )


# ===========================================
# Login
# ===========================================

@router.post(
    "/login",
    summary="Login user",
    description="Authenticate user with email and password."
)
async def login(
    credentials: UserLogin,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Login with email and password.
    
    Returns:
    - **access_token**: JWT access token (expires in 30 minutes)
    - **refresh_token**: Refresh token (valid for 7 days)
    - **token_type**: Always "bearer"
    - **user**: User information
    """
    user, error = await auth_service.authenticate_user(
        email=credentials.email,
        password=credentials.password
    )
    
    if error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error,
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Create response with tokens
    response_data = {
        "access_token": user["access_token"],
        "refresh_token": user["refresh_token"],
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user.get("username"),
            "role": user.get("role", "user"),
            "subscription_plan": user["subscription_plan"]
        }
    }
    
    logger.info(f"User logged in: {credentials.email}")
    
    return response_data


# ===========================================
# Logout
# ===========================================

@router.post(
    "/logout",
    summary="Logout user",
    description="Revoke refresh token and logout."
)
async def logout(
    response: Response,
    refresh_token: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Logout user by revoking their refresh token.
    
    - **refresh_token**: The refresh token to revoke
    """
    success = await auth_service.logout(refresh_token)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already revoked token"
        )
    
    # Clear response cookies if any
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")
    
    return {"message": "Successfully logged out"}


# ===========================================
# Refresh Token
# ===========================================

@router.post(
    "/refresh",
    summary="Refresh access token",
    description="Get new access token using refresh token."
)
async def refresh_token(
    refresh_token: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh access token using refresh token.
    
    - **refresh_token**: Valid refresh token from login
    """
    tokens, error = await auth_service.refresh_tokens(refresh_token)
    
    if error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error,
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return tokens


# ===========================================
# Email Verification
# ===========================================

@router.get(
    "/verify-email/{token}",
    summary="Verify email address",
    description="Verify user's email using token from verification email."
)
async def verify_email(
    token: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Verify email using token.
    
    - **token**: Verification token sent to email
    """
    success, message = await auth_service.verify_email(token)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    
    return {"message": message}


# ===========================================
# Password Reset
# ===========================================

@router.post(
    "/forgot-password",
    summary="Request password reset",
    description="Send password reset email."
)
async def forgot_password(
    request: PasswordResetRequest,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Request password reset email.
    
    - **email**: User's email address
    
    Note: Always returns success to prevent email enumeration.
    """
    # Find user
    user = await db.users.find_one({"email": request.email.lower()})
    
    if not user:
        # Don't reveal if email exists
        return {"message": "If the email exists, a reset link has been sent"}
    
    # Generate reset token and save it
    # In production, send email with reset link
    # For now, just log it
    import secrets
    reset_token = secrets.token_urlsafe(32)
    
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"reset_token": reset_token, "reset_token_expires": True}}
    )
    
    logger.info(f"Password reset requested for: {request.email}")
    logger.info(f"Reset token (for testing): {reset_token}")
    
    return {"message": "If the email exists, a reset link has been sent"}


@router.post(
    "/reset-password",
    summary="Reset password",
    description="Reset password using token from email."
)
async def reset_password(
    data: PasswordResetConfirm,
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Reset password using token.
    
    - **token**: Reset token from email
    - **new_password**: New password
    """
    # Find user by token
    user = await db.users.find_one({"reset_token": data.token})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Hash new password
    new_password_hash = auth_service.hash_password(data.new_password)
    
    # Update password and clear reset token
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": new_password_hash,
                "reset_token": None,
                "reset_token_expires": None,
                "updated_at": user.get("updated_at")
            }
        }
    )
    
    logger.info(f"Password reset completed for user")
    
    return {"message": "Password has been reset successfully"}


# ===========================================
# Change Password (Authenticated)
# ===========================================

@router.post(
    "/change-password",
    summary="Change password",
    description="Change password for authenticated user."
)
async def change_password(
    data: PasswordChange,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Change password for authenticated user.
    
    - **current_password**: Current password
    - **new_password**: New password
    """
    # Verify current password
    if not auth_service.verify_password(
        data.current_password,
        current_user["password_hash"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Hash new password
    new_password_hash = auth_service.hash_password(data.new_password)
    
    # Update password
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "password_hash": new_password_hash,
                "updated_at": current_user.get("updated_at")
            }
        }
    )
    
    logger.info(f"Password changed for user {current_user['email']}")
    
    return {"message": "Password changed successfully"}
