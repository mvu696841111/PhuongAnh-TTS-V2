"""
Main FastAPI application for PhuongAnh-TTS Backend.
Entry point for the API server.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from core.config import get_settings
from core.database import Database, RedisClient
from api.routes import auth_router, user_router, audio_router, admin_router, subscription_router, payment_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Manages database and Redis connections on startup/shutdown.
    """
    # Startup
    logger.info("=" * 60)
    logger.info(" PhuongAnh-TTS Backend Starting...")
    logger.info("=" * 60)
    
    try:
        # Connect to MongoDB
        await Database.connect()
        logger.info("✓ MongoDB connected")
        
        # Connect to Redis
        await RedisClient.connect()
        logger.info("✓ Redis connected")
        
    except Exception as e:
        logger.error(f"✗ Failed to connect to services: {e}")
        raise
    
    logger.info("=" * 60)
    logger.info(" PhuongAnh-TTS Backend Ready!")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info(" Shutting down...")
    
    await Database.disconnect()
    await RedisClient.disconnect()
    
    logger.info("✓ PhuongAnh-TTS Backend stopped")


# Create FastAPI app
app = FastAPI(
    title="PhuongAnh-TTS API",
    description="""
    ## PhuongAnh-TTS - Vietnamese Text-to-Speech API
    
    Hệ thống Text-to-Speech tiếng Việt chất lượng cao.
    
    ### Tính năng
    - **TTS Generation**: Chuyển văn bản thành giọng nói với nhiều giọng đọc
    - **Voice Cloning**: Clone giọng nói từ audio mẫu (Plus/Pro)
    - **Presets**: 4 giọng đọc có sẵn (Ly, Tuyên, Vĩnh, Đoan)
    
    ### Giới hạn
    - **Free**: 10 audio/ngày, 10,000 ký tự/tháng
    - **Plus**: 100 audio/ngày, 100,000 ký tự/tháng
    - **Pro**: Không giới hạn audio, 500,000 ký tự/tháng
    """,
    version="2.7.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Get settings
settings = get_settings()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================
# Health Check
# ===========================================

@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check if the API is running."
)
async def health_check():
    """
    Health check endpoint.
    Returns OK if the API is running.
    """
    return {
        "status": "healthy",
        "service": "phuonganh-tts-api",
        "version": "2.7.0"
    }


# ===========================================
# Root Endpoint
# ===========================================

@app.get(
    "/",
    tags=["Root"],
    summary="API root",
    description="Get API information."
)
async def root():
    """
    API root endpoint.
    Returns basic API information.
    """
    return {
        "name": "PhuongAnh-TTS API",
        "version": "2.7.0",
        "docs": "/docs",
        "health": "/health"
    }


# ===========================================
# Mount Routes
# ===========================================

app.include_router(auth_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(admin_router)  # Already has /api/admin prefix
app.include_router(subscription_router)  # Already has /api/subscription prefix
app.include_router(payment_router)  # Already has /api/payment prefix


# ===========================================
# Global Exception Handler
# ===========================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for unhandled errors.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred. Please try again later.",
            "error": str(exc) if settings.DEBUG else None
        }
    )


# ===========================================
# Run Server (Development)
# ===========================================

if __name__ == "__main__":
    import uvicorn
    import sys
    import os

    # Ensure backend directory is in path for imports
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Get port from env or default to 8000
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=port,
        reload=settings.RELOAD,
        workers=1,  # Use 1 worker in development
        log_level=settings.LOG_LEVEL.lower()
    )
