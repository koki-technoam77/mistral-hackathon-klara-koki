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
    "hackernews_frontpage": "hackernews",
    "hackernews_get_item": "hackernews",
    "hackernews_latest": "hackernews",
    "hackernews_today": "hackernews",
    "hackernews_get_user": "hackernews",
}

# Apps that require OAuth (need auth_config_id)
OAUTH_APPS = frozenset(["gmail", "googlecalendar", "slack", "todoist"])

# Apps that work without auth (no-auth toolkits)
NO_AUTH_APPS = frozenset(["hackernews"])

# Deduplicated list of supported apps for UI
SUPPORTED_APPS = sorted(set(ACTION_TO_APP.values()))


class ComposioAuthService:
    def __init__(self, config):
        self._config = config
        self._toolset = None
        self._auth_config_ids: dict[str, str] = {}
        self._build_auth_config_map(config)
        self._init_sdk()

    def _build_auth_config_map(self, config) -> None:
        """Build app→auth_config_id mapping from config."""
        mapping = {
            "gmail": getattr(config, "composio_auth_config_gmail", ""),
            "googlecalendar": getattr(config, "composio_auth_config_googlecalendar", ""),
            "slack": getattr(config, "composio_auth_config_slack", ""),
            "todoist": getattr(config, "composio_auth_config_todoist", ""),
        }
        self._auth_config_ids = {k: v for k, v in mapping.items() if v}
        if self._auth_config_ids:
            logger.info("Composio auth configs loaded: %s", list(self._auth_config_ids.keys()))

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
            # No-auth apps are always available
            if app_name in NO_AUTH_APPS:
                results.append({
                    "app": app_name,
                    "status": "active",
                    "auth_type": "none",
                    "connected_account_id": None,
                })
                continue

            try:
                entity = self._toolset.get_entity(id=entity_id)
                conn = await asyncio.to_thread(entity.get_connection, app=app_name)
                results.append({
                    "app": app_name,
                    "status": "active",
                    "connected_account_id": conn.id,
                })
            except Exception:
                # Check if auth_config_id is set for this app
                has_config = app_name in self._auth_config_ids
                results.append({
                    "app": app_name,
                    "status": "not_connected" if has_config else "not_configured",
                    "connected_account_id": None,
                })
        return results

    async def initiate_connection(self, entity_id: str, app_name: str, redirect_url: str) -> dict:
        """Start OAuth flow for a specific app using auth_config_id. Returns redirect URL."""
        if not self._toolset:
            return {"status": "error", "error": "Composio not configured"}

        if app_name not in SUPPORTED_APPS:
            return {"status": "error", "error": f"Unsupported app: {app_name}"}

        auth_config_id = self._auth_config_ids.get(app_name)
        if not auth_config_id:
            return {
                "status": "error",
                "error": f"No Auth Config ID set for {app_name}. "
                         f"Set COMPOSIO_AUTH_CONFIG_{app_name.upper()} env var.",
            }

        try:
            entity = self._toolset.get_entity(id=entity_id)
            logger.info(
                "Initiating Composio connection: app=%s, entity=%s, auth_config=%s",
                app_name, entity_id, auth_config_id,
            )
            connection_request = await asyncio.to_thread(
                entity.initiate_connection,
                app_name=app_name,
                auth_config_id=auth_config_id,
                redirect_url=redirect_url,
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
