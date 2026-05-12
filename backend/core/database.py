"""
Database connection module for PhuongAnh-TTS Backend.
Handles MongoDB and Redis connections using Motor (async driver).
"""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import MongoClient
from redis import asyncio as aioredis

from core.config import get_settings

logger = logging.getLogger(__name__)


class Database:
    """
    MongoDB connection manager using Motor (async driver).
    Implements singleton pattern for connection reuse.
    """

    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def connect(cls) -> None:
        """
        Establish connection to MongoDB.
        Call this on application startup.
        """
        if cls._client is not None:
            logger.warning("Database already connected")
            return

        settings = get_settings()
        
        try:
            cls._client = AsyncIOMotorClient(
                settings.MONGODB_URI,
                maxPoolSize=50,
                minPoolSize=10,
                maxIdleTimeMS=30000,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
            )
            
            # Verify connection
            await cls._client.admin.command("ping")
            
            cls._db = cls._client[settings.MONGODB_DB_NAME]
            
            logger.info(f"✓ Connected to MongoDB: {settings.MONGODB_DB_NAME}")
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to MongoDB: {e}")
            raise

    @classmethod
    async def disconnect(cls) -> None:
        """
        Close MongoDB connection.
        Call this on application shutdown.
        """
        if cls._client is not None:
            cls._client.close()
            cls._client = None
            cls._db = None
            logger.info("✓ Disconnected from MongoDB")

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        """
        Get database instance.
        
        Returns:
            AsyncIOMotorDatabase: The database instance
            
        Raises:
            RuntimeError: If database is not connected
        """
        if cls._db is None:
            raise RuntimeError(
                "Database not connected. Call Database.connect() first."
            )
        return cls._db

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        """
        Get MongoDB client instance.
        
        Returns:
            AsyncIOMotorClient: The client instance
            
        Raises:
            RuntimeError: If client is not connected
        """
        if cls._client is None:
            raise RuntimeError(
                "Database not connected. Call Database.connect() first."
            )
        return cls._client


class RedisClient:
    """
    Redis connection manager using aioredis.
    Implements singleton pattern for connection reuse.
    """

    _client: Optional[aioredis.Redis] = None

    @classmethod
    async def connect(cls) -> None:
        """
        Establish connection to Redis.
        Call this on application startup.
        """
        if cls._client is not None:
            logger.warning("Redis already connected")
            return

        settings = get_settings()
        
        try:
            cls._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
            )
            
            # Verify connection
            await cls._client.ping()
            
            logger.info(f"✓ Connected to Redis: {settings.REDIS_URL}")
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            raise

    @classmethod
    async def disconnect(cls) -> None:
        """
        Close Redis connection.
        Call this on application shutdown.
        """
        if cls._client is not None:
            await cls._client.close()
            cls._client = None
            logger.info("✓ Disconnected from Redis")

    @classmethod
    def get_client(cls) -> aioredis.Redis:
        """
        Get Redis client instance.
        
        Returns:
            aioredis.Redis: The Redis client
            
        Raises:
            RuntimeError: If Redis is not connected
        """
        if cls._client is None:
            raise RuntimeError(
                "Redis not connected. Call RedisClient.connect() first."
            )
        return cls._client


# Convenience functions
def get_database() -> AsyncIOMotorDatabase:
    """Get database instance."""
    return Database.get_db()


def get_redis() -> aioredis.Redis:
    """Get Redis client instance."""
    return RedisClient.get_client()
