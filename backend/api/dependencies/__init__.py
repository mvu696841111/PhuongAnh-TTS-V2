"""
API Dependencies for PhuongAnh-TTS Backend.
Provides authentication, rate limiting, and service injection.
"""

import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from core.config import get_settings, get_subscription_limits
from services.auth_service import AuthService
from services.user_service import UserService
from services.subscription_service import SubscriptionService
from services.audio_service import AudioService

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT tokens
security = HTTPBearer(auto_error=False)


# ===========================================
# Database Dependency
# ===========================================

async def get_db() -> AsyncIOMotorDatabase:
    """Get database instance."""
    return get_database()


# ===========================================
# Service Dependencies
# ===========================================

async def get_auth_service(
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> AuthService:
    """Get auth service instance."""
    return AuthService(db)


async def get_user_service(
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> UserService:
    """Get user service instance."""
    return UserService(db)


async def get_subscription_service(
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> SubscriptionService:
    """Get subscription service instance."""
    return SubscriptionService(db)


async def get_audio_service(
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> AudioService:
    """Get audio service instance."""
    return AudioService(db)


# ===========================================
# Authentication Dependencies
# ===========================================

async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> Optional[dict]:
    """
    Get current user if authenticated, otherwise None.
    Does not raise error if not authenticated.
    """
    if not credentials:
        return None
    
    try:
        auth_service = AuthService(db)
        payload = auth_service.verify_access_token(credentials.credentials)
        
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        user = await auth_service.get_user_by_id(user_id)
        return user
        
    except Exception as e:
        logger.debug(f"Optional auth failed: {e}")
        return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    """
    Get current authenticated user.
    Raises HTTPException if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        auth_service = AuthService(db)
        payload = auth_service.verify_access_token(credentials.credentials)
        
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        user = await auth_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Store user in request state for later access
        request.state.user = user
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"}
        )


# ===========================================
# Permission Dependencies
# ===========================================

class RequirePlan:
    """
    Dependency class for checking subscription plan.
    Usage: @router.get("/feature", dependencies=[Depends(RequirePlan("plus"))])
    """
    
    def __init__(self, min_plan: str):
        self.min_plan = min_plan
        self.plan_hierarchy = {"free": 0, "plus": 1, "pro": 2}
    
    async def __call__(
        self,
        user: dict = Depends(get_current_user),
        subscription_service: SubscriptionService = Depends(get_subscription_service)
    ) -> dict:
        """Check if user has required plan level."""
        user_plan = user.get("subscription_plan", "free")
        user_level = self.plan_hierarchy.get(user_plan, 0)
        required_level = self.plan_hierarchy.get(self.min_plan, 0)
        
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires {self.min_plan} plan or higher. Please upgrade your subscription."
            )
        
        return user


class RequirePermission:
    """
    Dependency class for checking specific permission.
    Usage: @router.get("/api-feature", dependencies=[Depends(RequirePermission("api:access"))])
    """
    
    def __init__(self, permission: str):
        self.permission = permission
    
    async def __call__(
        self,
        user: dict = Depends(get_current_user),
        subscription_service: SubscriptionService = Depends(get_subscription_service)
    ) -> dict:
        """Check if user has required permission."""
        has_permission = await subscription_service.has_permission(
            user["_id"], self.permission
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires the '{self.permission}' permission. Please upgrade your plan."
            )
        
        return user


# ===========================================
# Rate Limiting
# ===========================================

async def check_rate_limit(
    request: Request,
    user: Optional[dict] = Depends(get_current_user_optional)
) -> Optional[dict]:
    """
    Check rate limiting based on user.
    For unauthenticated users, use IP-based limiting.
    """
    # This would integrate with Redis for actual rate limiting
    # For now, return user (rate limiting handled by slowapi middleware)
    return user


# ===========================================
# Usage Limit Checks
# ===========================================

async def check_usage_limit(
    text_length: int,
    user: dict = Depends(get_current_user),
    audio_service: AudioService = Depends(get_audio_service)
) -> bool:
    """
    Check if user can generate audio based on usage limits.
    Raises HTTPException if limit exceeded.
    """
    user_id = str(user["_id"])
    
    can_generate, error_message = await audio_service.check_usage_limits(
        user_id, text_length
    )
    
    if not can_generate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_message
        )
    
    return True
