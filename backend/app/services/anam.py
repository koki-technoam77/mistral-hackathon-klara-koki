import logging

import httpx

logger = logging.getLogger(__name__)

ANAM_SESSION_URL = "https://api.anam.ai/v1/auth/session-token"

# Default avatar from Anam docs (Cara)
DEFAULT_AVATAR_ID = "30fa96d0-26c4-4e55-94a0-517025942e18"


class AnamService:
    def __init__(self, config):
        self.api_key = config.anam_api_key
        self.avatar_id = config.anam_avatar_id or DEFAULT_AVATAR_ID
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=10.0,
        )

    async def create_session(self) -> dict:
        """Create an Anam session token with audio passthrough enabled."""
        if not self.api_key:
            raise ValueError("ANAM_API_KEY is not configured")

        logger.info("Creating Anam session with avatar_id=%s", self.avatar_id)
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
        if response.status_code != 200:
            body = response.text
            logger.error(
                "Anam session-token API returned %d: %s",
                response.status_code,
                body,
            )
        response.raise_for_status()
        data = response.json()
        logger.info("Anam session token received (length=%d)", len(data.get("sessionToken", "")))
        return data

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
