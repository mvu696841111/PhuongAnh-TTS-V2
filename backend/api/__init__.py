"""
API module initialization.
"""

from api.routes import auth_router, user_router, audio_router

__all__ = [
    "auth_router",
    "user_router",
    "audio_router",
]
