import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Map KotoFlow action names to Composio app names
ACTION_TO_APP = {
    "send_email": "gmail",
    "list_emails": "gmail",
    "create_calendar_event": "googlecalendar",
    "create_task": "todoist",
    "send_slack_message": "slack",
}

# Deduplicated list of supported apps for UI
SUPPORTED_APPS = sorted(set(ACTION_TO_APP.values()))


class ComposioAuthService:
    def __init__(self, config):
        self._config = config
        self._toolset = None
        self._init_sdk()

    def _init_sdk(self) -> None:
        if self._toolset or not self._config.composio_api_key:
            return
        try:
            from composio import ComposioToolSet
            self._toolset = ComposioToolSet(api_key=self._config.composio_api_key)
            logger.info("Composio auth SDK initialized")
        except Exception:
            logger.error("Composio auth SDK init failed", exc_info=True)

    @property
    def available(self) -> bool:
        if not self._toolset and self._config.composio_api_key:
            self._init_sdk()
        return self._toolset is not None

    async def get_connections(self, entity_id: str) -> list[dict]:
        """Get all active connections for an entity (user)."""
        if not self._toolset:
            return []

        results = []
        for app_name in SUPPORTED_APPS:
            try:
                entity = self._toolset.get_entity(id=entity_id)
                conn = await asyncio.to_thread(entity.get_connection, app=app_name)
                results.append({
                    "app": app_name,
                    "status": "active",
                    "connected_account_id": conn.id,
                })
            except Exception:
                results.append({
                    "app": app_name,
                    "status": "not_connected",
                    "connected_account_id": None,
                })
        return results

    async def initiate_connection(self, entity_id: str, app_name: str, redirect_url: str) -> dict:
        """Start OAuth flow for a specific app. Returns redirect URL."""
        if not self._toolset:
            return {"status": "error", "error": "Composio not configured"}

        if app_name not in SUPPORTED_APPS:
            return {"status": "error", "error": f"Unsupported app: {app_name}"}

        try:
            entity = self._toolset.get_entity(id=entity_id)
            connection_request = await asyncio.to_thread(
                entity.initiate_connection,
                app_name=app_name,
                redirect_url=redirect_url,
                auth_mode="OAUTH2",
            )
            return {
                "status": "pending",
                "redirect_url": connection_request.redirectUrl,
                "connected_account_id": connection_request.connectedAccountId,
            }
        except Exception:
            logger.error("Failed to initiate Composio connection for %s", app_name, exc_info=True)
            return {"status": "error", "error": "Failed to initiate connection"}

    async def check_connection_status(self, entity_id: str, app_name: str) -> dict:
        """Check if a specific app is connected for this entity."""
        if not self._toolset:
            return {"app": app_name, "status": "not_configured"}

        try:
            entity = self._toolset.get_entity(id=entity_id)
            conn = await asyncio.to_thread(entity.get_connection, app=app_name)
            return {
                "app": app_name,
                "status": "active",
                "connected_account_id": conn.id,
            }
        except Exception:
            return {
                "app": app_name,
                "status": "not_connected",
                "connected_account_id": None,
            }

    def get_required_apps(self, workflow_actions: list[str]) -> list[str]:
        """Given a list of workflow actions, return which Composio apps are needed."""
        apps = set()
        for action in workflow_actions:
            if action in ACTION_TO_APP:
                apps.add(ACTION_TO_APP[action])
        return sorted(apps)
