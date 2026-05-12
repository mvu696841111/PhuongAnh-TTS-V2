"""
Authentication service for PhuongAnh-TTS Backend.
Handles user authentication, JWT tokens, and security.
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from passlib.context import CryptContext
from jose import jwt, JWTError

from core.config import get_settings
from core.database import get_database

logger = logging.getLogger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """
    Authentication service for user login, registration, and token management.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings = get_settings()
        self.users = db.users
        self.sessions = db.sessions

    # ===========================================
    # Password Hashing
    # ===========================================

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password string
        """
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to check against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False

    # ===========================================
    # JWT Token Management
    # ===========================================

    def create_access_token(self, user_id: str, **extra_claims) -> str:
        """
        Create a JWT access token.
        
        Args:
            user_id: User ID to encode in token
            **extra_claims: Additional claims to include in token
            
        Returns:
            Encoded JWT token string
        """
        expire = datetime.utcnow() + timedelta(
            minutes=self.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access",
            **extra_claims
        }
        
        token = jwt.encode(
            payload,
            self.settings.JWT_SECRET_KEY,
            algorithm=self.settings.JWT_ALGORITHM
        )
        
        return token

    def create_refresh_token(self, user_id: str) -> Tuple[str, str]:
        """
        Create a refresh token and store it in database.
        
        Args:
            user_id: User ID to create token for
            
        Returns:
            Tuple of (token, token_hash)
        """
        expire = datetime.utcnow() + timedelta(
            days=self.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        
        # Create a secure random token
        token = secrets.token_urlsafe(64)
        token_hash = self.hash_password(token)
        
        return token, token_hash

    def create_tokens(self, user_id: str, **extra_claims) -> dict:
        """
        Create both access and refresh tokens for a user.
        
        Args:
            user_id: User ID to create tokens for
            **extra_claims: Additional claims for access token
            
        Returns:
            Dictionary with access_token, refresh_token, token_type
        """
        access_token = self.create_access_token(user_id, **extra_claims)
        refresh_token, refresh_token_hash = self.create_refresh_token(user_id)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "refresh_token_hash": refresh_token_hash,
            "token_type": "bearer"
        }

    def verify_access_token(self, token: str) -> Optional[dict]:
        """
        Verify and decode an access token.
        
        Args:
            token: JWT token to verify
            
        Returns:
            Decoded token payload or None if invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.settings.JWT_SECRET_KEY,
                algorithms=[self.settings.JWT_ALGORITHM]
            )
            
            if payload.get("type") != "access":
                return None
                
            return payload
            
        except JWTError:
            return None

    # ===========================================
    # User Registration
    # ===========================================

    async def register_user(
        self,
        email: str,
        password: str,
        username: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Tuple[Optional[dict], Optional[str]]:
        """
        Register a new user.
        
        Args:
            email: User email
            password: Plain text password
            username: Optional username
            phone: Optional phone number
            
        Returns:
            Tuple of (user_dict, error_message)
        """
        try:
            # Check if email already exists
            existing = await self.users.find_one({"email": email})
            if existing:
                return None, "Email already registered"
            
            # Create user document
            now = datetime.utcnow()
            verification_token = secrets.token_urlsafe(32)
            
            user_doc = {
                "email": email.lower().strip(),
                "password_hash": self.hash_password(password),
                "role": "user",
                "username": username,
                "phone": phone,
                "subscription_plan": "free",
                "subscription_status": "active",
                "subscription_expires_at": None,
                "is_verified": False,
                "verification_token": verification_token,
                "last_login": None,
                "created_at": now,
                "updated_at": now,
                "metadata": {
                    "registration_source": "web",
                    "email_verified": False,
                }
            }
            
            result = await self.users.insert_one(user_doc)
            user_id = str(result.inserted_id)
            
            # Create initial subscription record
            await self.db.subscriptions.insert_one({
                "user_id": ObjectId(user_id),
                "plan": "free",
                "started_at": now,
                "expires_at": None,
                "auto_renew": False,
                "payment_history": [],
                "status": "active"
            })
            
            # Log the registration
            await self.db.usage_logs.insert_one({
                "user_id": ObjectId(user_id),
                "action": "register",
                "timestamp": now,
                "metadata": {"source": "web"}
            })
            
            logger.info(f"✓ User registered: {email}")
            
            return {
                "id": user_id,
                "email": email,
                "username": username,
                "subscription_plan": "free",
                "verification_token": verification_token
            }, None
            
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return None, "Registration failed"

    # ===========================================
    # User Login
    # ===========================================

    async def authenticate_user(
        self,
        email: str,
        password: str
    ) -> Tuple[Optional[dict], Optional[str]]:
        """
        Authenticate a user by email and password.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            Tuple of (user_dict, error_message)
        """
        try:
            # Find user by email
            user = await self.users.find_one({"email": email.lower().strip()})
            
            if not user:
                return None, "Invalid email or password"
            
            # Verify password
            if not self.verify_password(password, user["password_hash"]):
                return None, "Invalid email or password"
            
            # Update last login
            now = datetime.utcnow()
            await self.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "last_login": now,
                        "updated_at": now
                    }
                }
            )
            
            # Create tokens
            tokens = self.create_tokens(
                str(user["_id"]),
                email=user["email"],
                plan=user.get("subscription_plan", "free")
            )
            
            # Store refresh token hash in database
            await self.sessions.insert_one({
                "user_id": user["_id"],
                "refresh_token_hash": tokens["refresh_token_hash"],
                "created_at": now,
                "expires_at": now + timedelta(days=self.settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
                "is_revoked": False,
                "user_agent": None,
                "ip_address": None
            })
            
            # Log the login
            await self.db.usage_logs.insert_one({
                "user_id": user["_id"],
                "action": "login",
                "timestamp": now,
                "metadata": {}
            })
            
            logger.info(f"✓ User logged in: {email}")
            
            return {
                "id": str(user["_id"]),
                "email": user["email"],
                "username": user.get("username"),
                "role": user.get("role", "user"),
                "subscription_plan": user.get("subscription_plan", "free"),
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": tokens["token_type"]
            }, None
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return None, "Authentication failed"

    # ===========================================
    # Token Refresh
    # ===========================================

    async def refresh_tokens(self, refresh_token: str) -> Tuple[Optional[dict], Optional[str]]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Refresh token from login
            
        Returns:
            Tuple of (tokens_dict, error_message)
        """
        try:
            # Find session with this refresh token
            session = await self.sessions.find_one({
                "refresh_token_hash": self.hash_password(refresh_token),
                "is_revoked": False,
                "expires_at": {"$gt": datetime.utcnow()}
            })
            
            if not session:
                return None, "Invalid or expired refresh token"
            
            # Get user
            user = await self.users.find_one({"_id": session["user_id"]})
            if not user:
                return None, "User not found"
            
            # Create new tokens
            tokens = self.create_tokens(
                str(user["_id"]),
                email=user["email"],
                plan=user.get("subscription_plan", "free")
            )
            
            # Update session with new refresh token hash
            await self.sessions.update_one(
                {"_id": session["_id"]},
                {"$set": {"refresh_token_hash": tokens["refresh_token_hash"]}}
            )
            
            return {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": tokens["token_type"]
            }, None
            
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return None, "Token refresh failed"

    # ===========================================
    # Logout
    # ===========================================

    async def logout(self, refresh_token: str) -> bool:
        """
        Logout user by revoking their refresh token.
        
        Args:
            refresh_token: Refresh token to revoke
            
        Returns:
            True if successful
        """
        try:
            result = await self.sessions.update_one(
                {"refresh_token_hash": self.hash_password(refresh_token)},
                {"$set": {"is_revoked": True}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False

    # ===========================================
    # Get User by ID
    # ===========================================

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """
        Get user by ID.
        
        Args:
            user_id: User ID string
            
        Returns:
            User document or None
        """
        try:
            user = await self.users.find_one({"_id": ObjectId(user_id)})
            if user:
                user["_id"] = str(user["_id"])
            return user
        except Exception:
            return None

    # ===========================================
    # Email Verification
    # ===========================================

    async def verify_email(self, token: str) -> Tuple[bool, Optional[str]]:
        """
        Verify user email using token.
        
        Args:
            token: Verification token from email
            
        Returns:
            Tuple of (success, message)
        """
        try:
            user = await self.users.find_one({"verification_token": token})
            if not user:
                return False, "Invalid verification token"
            
            await self.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "is_verified": True,
                        "verification_token": None,
                        "updated_at": datetime.utcnow()
                    },
                    "$unset": {"metadata.email_verified": ""}
                }
            )
            
            return True, "Email verified successfully"
            
        except Exception as e:
            logger.error(f"Email verification error: {e}")
            return False, "Verification failed"


# Factory function
def get_auth_service() -> AuthService:
    """Get AuthService instance."""
    return AuthService(get_database())
