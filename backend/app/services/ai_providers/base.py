"""Abstract base class for AI providers with OAuth token management."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.models.ai_team import AIProvider, ProviderResult

logger = logging.getLogger(__name__)


class OAuthTokenManager:
    """Manages OAuth token lifecycle for subscription-based AI provider APIs."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: Optional[list[str]] = None,
    ):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes or []
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    async def get_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if expired."""
        if not self.client_id or not self.client_secret:
            return None

        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        return await self._refresh_token()

    async def _refresh_token(self) -> Optional[str]:
        """Fetch a new access token via client_credentials grant."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
                if self.scopes:
                    payload["scope"] = " ".join(self.scopes)

                resp = await client.post(self.token_url, data=payload)
                resp.raise_for_status()

                data = resp.json()
                self._access_token = data["access_token"]
                self._expires_at = time.time() + data.get("expires_in", 3600)
                logger.info("OAuth token refreshed for %s", self.token_url)
                return self._access_token

        except Exception:
            logger.error("OAuth token refresh failed for %s", self.token_url, exc_info=True)
            return None


class BaseAIProvider(ABC):
    """Base class for all AI providers."""

    def __init__(
        self,
        provider: AIProvider,
        api_key: str,
        oauth_client_id: str = "",
        oauth_client_secret: str = "",
    ):
        self.provider = provider
        self.api_key = api_key
        self._oauth: Optional[OAuthTokenManager] = None

        if oauth_client_id and oauth_client_secret:
            self._oauth = OAuthTokenManager(
                token_url=self._get_token_url(),
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                scopes=self._get_scopes(),
            )

    @abstractmethod
    def _get_token_url(self) -> str:
        """Return the OAuth token endpoint for this provider."""

    def _get_scopes(self) -> list[str]:
        """Return OAuth scopes needed. Override in subclass if needed."""
        return []

    async def _get_auth_key(self) -> str:
        """Get the active auth key: OAuth token if available, else API key."""
        if self._oauth:
            token = await self._oauth.get_token()
            if token:
                return token
        return self.api_key

    def is_configured(self) -> bool:
        """Check if this provider has credentials configured."""
        return bool(self.api_key) or (
            self._oauth is not None
            and bool(self._oauth.client_id)
        )

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        context: Optional[dict[str, Any]] = None,
    ) -> ProviderResult:
        """Generate a response from this AI provider."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable and responsive."""
