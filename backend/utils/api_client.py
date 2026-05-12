"""
API client for PhuongAnh-TTS Backend.
Can be used by frontend applications to interact with the API.
"""

import httpx
from typing import Optional, Dict, Any
from urllib.parse import urljoin


class PhuongAnhAPIClient:
    """
    Client for PhuongAnh-TTS API.
    
    Usage:
        client = PhuongAnhAPIClient(base_url="http://localhost:8000")
        client.register(email="user@example.com", password="password123")
        client.login(email="user@example.com", password="password123")
        response = client.generate_tts(text="Xin chào", voice_id="Ly")
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.user: Optional[Dict[str, Any]] = None
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None,
        files: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to API."""
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        
        if files:
            # Multipart request
            response = await self._client.request(
                method=method,
                url=url,
                data=data,
                files=files,
                headers={"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
            )
        else:
            response = await self._client.request(
                method=method,
                url=url,
                json=data,
                headers=self._get_headers()
            )
        
        if response.status_code >= 400:
            error_detail = response.json().get("detail", response.text)
            raise Exception(f"API Error {response.status_code}: {error_detail}")
        
        return response.json()

    # ===========================================
    # Authentication
    # ===========================================

    async def register(
        self,
        email: str,
        password: str,
        username: Optional[str] = None
    ) -> Dict[str, Any]:
        """Register a new user."""
        return await self._request(
            "POST",
            "/api/auth/register",
            data={"email": email, "password": password, "username": username}
        )

    async def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login user and store tokens."""
        response = await self._request(
            "POST",
            "/api/auth/login",
            data={"email": email, "password": password}
        )
        
        self.access_token = response.get("access_token")
        self.refresh_token = response.get("refresh_token")
        self.user = response.get("user")
        
        return response

    async def logout(self) -> Dict[str, Any]:
        """Logout user and revoke tokens."""
        if not self.refresh_token:
            raise Exception("Not logged in")
        
        response = await self._request(
            "POST",
            "/api/auth/logout",
            data={"refresh_token": self.refresh_token}
        )
        
        self.access_token = None
        self.refresh_token = None
        self.user = None
        
        return response

    async def refresh(self) -> Dict[str, Any]:
        """Refresh access token."""
        if not self.refresh_token:
            raise Exception("No refresh token")
        
        response = await self._request(
            "POST",
            "/api/auth/refresh",
            data={"refresh_token": self.refresh_token}
        )
        
        self.access_token = response.get("access_token")
        self.refresh_token = response.get("refresh_token")
        
        return response

    async def verify_email(self, token: str) -> Dict[str, Any]:
        """Verify email address."""
        return await self._request("GET", f"/api/auth/verify-email/{token}")

    # ===========================================
    # User
    # ===========================================

    async def get_profile(self) -> Dict[str, Any]:
        """Get user profile."""
        return await self._request("GET", "/api/user/profile")

    async def update_profile(
        self,
        username: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update user profile."""
        data = {}
        if username is not None:
            data["username"] = username
        if phone is not None:
            data["phone"] = phone
        return await self._request("PUT", "/api/user/profile", data=data)

    async def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return await self._request("GET", "/api/user/usage")

    async def get_subscription(self) -> Dict[str, Any]:
        """Get subscription info."""
        return await self._request("GET", "/api/user/subscription")

    async def get_plans(self) -> Dict[str, Any]:
        """Get available subscription plans."""
        return await self._request("GET", "/api/user/subscription/plans")

    # ===========================================
    # Audio
    # ===========================================

    async def list_voices(self) -> Dict[str, Any]:
        """Get list of available voices."""
        return await self._request("GET", "/api/audio/voices")

    async def generate_tts(
        self,
        text: str,
        voice_id: str,
        format: str = "wav",
        speed: float = 1.0,
        temperature: float = 1.0
    ) -> Dict[str, Any]:
        """Generate TTS audio."""
        return await self._request(
            "POST",
            "/api/audio/generate",
            data={
                "text": text,
                "voice_id": voice_id,
                "format": format,
                "speed": speed,
                "temperature": temperature
            }
        )

    async def list_audios(
        self,
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """Get list of user's audio files."""
        return await self._request(
            "GET",
            f"/api/audio/list?page={page}&per_page={per_page}"
        )

    async def get_audio(self, audio_id: str) -> Dict[str, Any]:
        """Get audio file info."""
        return await self._request("GET", f"/api/audio/{audio_id}")

    async def delete_audio(self, audio_id: str) -> None:
        """Delete audio file."""
        await self._request("DELETE", f"/api/audio/{audio_id}")

    async def download_audio(self, audio_id: str) -> bytes:
        """Download audio file."""
        url = urljoin(self.base_url + "/", f"api/audio/{audio_id}/file")
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        response = await self._client.get(url, headers=headers)
        
        if response.status_code >= 400:
            raise Exception(f"Download failed: {response.status_code}")
        
        return response.content

    # ===========================================
    # Context Manager
    # ===========================================

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Synchronous wrapper
class SyncPhuongAnhAPIClient:
    """Synchronous wrapper for PhuongAnhAPIClient."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self._async_client = PhuongAnhAPIClient(base_url)

    def register(self, email: str, password: str, username: Optional[str] = None) -> Dict[str, Any]:
        """Register a new user."""
        import asyncio
        return asyncio.run(self._async_client.register(email, password, username))

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login user."""
        import asyncio
        return asyncio.run(self._async_client.login(email, password))

    def logout(self) -> Dict[str, Any]:
        """Logout user."""
        import asyncio
        return asyncio.run(self._async_client.logout())

    def get_profile(self) -> Dict[str, Any]:
        """Get user profile."""
        import asyncio
        return asyncio.run(self._async_client.get_profile())

    def generate_tts(
        self,
        text: str,
        voice_id: str,
        format: str = "wav"
    ) -> Dict[str, Any]:
        """Generate TTS audio."""
        import asyncio
        return asyncio.run(self._async_client.generate_tts(text, voice_id, format))

    def close(self):
        """Close the client."""
        import asyncio
        asyncio.run(self._async_client.close())
