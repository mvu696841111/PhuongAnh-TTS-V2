"""
API routes initialization.
"""

from api.routes.auth import router as auth_router
from api.routes.user import router as user_router
from api.routes.audio import router as audio_router
from api.routes.admin import router as admin_router
from api.routes.subscription import router as subscription_router
from api.routes.payment import router as payment_router
from api.routes.finance import router as finance_router

__all__ = [
    "auth_router",
    "user_router",
    "audio_router",
    "admin_router",
    "subscription_router",
    "payment_router",
    "finance_router",
]
