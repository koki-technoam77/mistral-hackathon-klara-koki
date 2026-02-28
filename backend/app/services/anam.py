import logging

import httpx

logger = logging.getLogger(__name__)

ANAM_SESSION_URL = "https://api.anam.ai/v1/auth/session-token"


class AnamService:
    def __init__(self, config):
        self.api_key = config.anam_api_key
        self.avatar_id = config.anam_avatar_id
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=10.0,
        )

    async def create_session(self) -> dict:
        """Create an Anam session token with audio passthrough enabled."""
        if not self.api_key:
            raise ValueError("ANAM_API_KEY is not configured")

        response = await self._client.post(
            ANAM_SESSION_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "personaConfig": {
                    "avatarId": self.avatar_id,
                    "enableAudioPassthrough": True,
                }
            },
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
