"""
Authentication service for phuonganh-tts Gradio app.
Handles login, register, logout with the backend API.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger("phuonganh.auth")

# Default backend URL - can be overridden via environment
DEFAULT_BACKEND_URL = os.getenv("TTS_BACKEND_URL", "http://localhost:8000")


@dataclass
class AuthUser:
    """Authenticated user data."""
    id: str
    email: str
    username: Optional[str] = None
    subscription_plan: str = "free"
    is_verified: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthUser":
        return cls(
            id=data.get("id", ""),
            email=data.get("email", ""),
            username=data.get("username"),
            subscription_plan=data.get("subscription_plan", "free"),
            is_verified=data.get("is_verified", False),
        )


class AuthService:
    """
    Authentication service for Gradio app.
    Manages user session with local storage for tokens.
    """

    _instance: Optional["AuthService"] = None
    _lock = threading.Lock()

    def __new__(cls, backend_url: str = DEFAULT_BACKEND_URL) -> "AuthService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, backend_url: str = DEFAULT_BACKEND_URL):
        if self._initialized:
            return
        self._initialized = True

        self.backend_url = backend_url.rstrip("/")
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.user: Optional[AuthUser] = None
        self._session_file = Path.home() / ".phuonganh_tts" / "session.json"
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_session()

    def _load_session(self) -> None:
        """Load session from local file."""
        try:
            if self._session_file.exists():
                data = json.loads(self._session_file.read_text())
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                user_data = data.get("user")
                if user_data:
                    self.user = AuthUser.from_dict(user_data)
                logger.info(f"Session loaded for user: {self.user.email if self.user else 'none'}")
        except Exception as e:
            logger.warning(f"Failed to load session: {e}")

    def _save_session(self) -> None:
        """Save session to local file."""
        try:
            data = {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "user": {
                    "id": self.user.id if self.user else None,
                    "email": self.user.email if self.user else None,
                    "username": self.user.username if self.user else None,
                    "subscription_plan": self.user.subscription_plan if self.user else None,
                    "is_verified": self.user.is_verified if self.user else None,
                } if self.user else None,
            }
            self._session_file.write_text(json.dumps(data, indent=2))
            logger.info("Session saved")
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")

    def _clear_session(self) -> None:
        """Clear session from local file."""
        try:
            if self._session_file.exists():
                self._session_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to clear session: {e}")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None,
        authenticated: bool = False,
    ) -> Dict[str, Any]:
        """Make HTTP request to backend API."""
        url = f"{self.backend_url}{path}"

        if authenticated and not self.access_token:
            raise Exception("Not authenticated. Please login first.")

        try:
            with httpx.Client(timeout=30.0) as client:
                if method == "GET":
                    response = client.get(url, headers=self._get_headers())
                elif method == "POST":
                    response = client.post(url, json=data, headers=self._get_headers())
                elif method == "PUT":
                    response = client.put(url, json=data, headers=self._get_headers())
                elif method == "DELETE":
                    response = client.delete(url, headers=self._get_headers())
                else:
                    raise ValueError(f"Unsupported method: {method}")

                if response.status_code >= 400:
                    try:
                        error_detail = response.json().get("detail", response.text)
                    except Exception:
                        error_detail = response.text
                    raise Exception(f"Lỗi {response.status_code}: {error_detail}")

                return response.json()

        except httpx.ConnectError:
            raise Exception(f"Không thể kết nối đến server. Vui lòng kiểm tra backend đang chạy tại {self.backend_url}")
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise

    def is_authenticated(self) -> bool:
        """Check if user is logged in."""
        return self.user is not None and self.access_token is not None

    def is_backend_available(self) -> bool:
        """Check if backend API is available."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.backend_url}/docs")
                return response.status_code == 200
        except Exception:
            return False

    def register(
        self,
        email: str,
        password: str,
        username: Optional[str] = None,
    ) -> AuthUser:
        """Register a new user."""
        data = {"email": email, "password": password}
        if username:
            data["username"] = username

        result = self._make_request("POST", "/api/auth/register", data=data)
        return AuthUser.from_dict(result)

    def login(self, email: str, password: str) -> AuthUser:
        """Login user and store tokens."""
        result = self._make_request(
            "POST",
            "/api/auth/login",
            data={"email": email, "password": password},
        )

        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")

        user_data = result.get("user", {})
        self.user = AuthUser.from_dict(user_data)

        self._save_session()
        logger.info(f"User logged in: {email}")

        return self.user

    def logout(self) -> None:
        """Logout user and revoke tokens."""
        if self.refresh_token:
            try:
                self._make_request(
                    "POST",
                    "/api/auth/logout",
                    data={"refresh_token": self.refresh_token},
                    authenticated=True,
                )
            except Exception as e:
                logger.warning(f"Logout API call failed: {e}")

        self.access_token = None
        self.refresh_token = None
        self.user = None
        self._clear_session()
        logger.info("User logged out")

    def refresh_access_token(self) -> bool:
        """Refresh access token using refresh token."""
        if not self.refresh_token:
            return False

        try:
            result = self._make_request(
                "POST",
                "/api/auth/refresh",
                data={"refresh_token": self.refresh_token},
            )
            self.access_token = result.get("access_token")
            self.refresh_token = result.get("refresh_token")
            self._save_session()
            return True
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")
            return False

    def get_user_info(self) -> Optional[AuthUser]:
        """Get current user info."""
        return self.user

    def get_usage_stats(self) -> Optional[Dict[str, Any]]:
        """Get user usage statistics."""
        if not self.is_authenticated():
            return None

        try:
            return self._make_request(
                "GET",
                "/api/user/usage",
                authenticated=True,
            )
        except Exception as e:
            logger.warning(f"Failed to get usage stats: {e}")
            return None

    def get_subscription_plans(self) -> Optional[list]:
        """Get available subscription plans."""
        try:
            result = self._make_request("GET", "/api/user/subscription/plans")
            return result if isinstance(result, list) else result.get("plans", [])
        except Exception as e:
            logger.warning(f"Failed to get plans: {e}")
            return None

    def get_plan_display_name(self, plan: str) -> str:
        """Get display name for plan."""
        names = {
            "free": "Free (Miễn phí)",
            "plus": "Plus (199,000đ/tháng)",
            "pro": "Pro (499,000đ/tháng)",
        }
        return names.get(plan, plan)


def get_auth_service(backend_url: str = DEFAULT_BACKEND_URL) -> AuthService:
    """Get or create AuthService singleton."""
    return AuthService(backend_url)
