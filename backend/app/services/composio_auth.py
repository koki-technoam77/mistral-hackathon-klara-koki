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
    # Google Sheets
    "sheets_create_row": "googlesheets",
    "sheets_query": "googlesheets",
    "sheets_lookup_row": "googlesheets",
    "sheets_get_schema": "googlesheets",
    # LinkedIn
    "linkedin_create_post": "linkedin",
    "linkedin_share_url": "linkedin",
    "linkedin_get_my_info": "linkedin",
    # Twitter / X
    "tweet": "twitter",
    "twitter_search": "twitter",
    "twitter_get_analytics": "twitter",
    # GitHub
    "github_create_issue": "github",
    "github_create_pr": "github",
    "github_star_repo": "github",
    "github_list_repos": "github",
    # Gemini (no auth)
    "gemini_generate": "gemini",
    "gemini_generate_image": "gemini",
    "gemini_embed": "gemini",
    # Hacker News (no auth)
    "hackernews_frontpage": "hackernews",
    "hackernews_get_item": "hackernews",
    "hackernews_latest": "hackernews",
    "hackernews_today": "hackernews",
    "hackernews_get_user": "hackernews",
}

# Apps that require OAuth (need auth_config_id)
OAUTH_APPS = frozenset([
    "gmail", "googlecalendar", "slack", "todoist",
    "googlesheets", "linkedin", "twitter", "github",
])

# Apps that work without auth (no-auth toolkits)
NO_AUTH_APPS = frozenset(["hackernews", "gemini"])

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
            "googlesheets": getattr(config, "composio_auth_config_googlesheets", ""),
            "linkedin": getattr(config, "composio_auth_config_linkedin", ""),
            "twitter": getattr(config, "composio_auth_config_twitter", ""),
            "github": getattr(config, "composio_auth_config_github", ""),
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
                "Initiating Composio connection: app=%s, entity=%s, integration_id=%s",
                app_name, entity_id, auth_config_id,
            )
            # auth_config_id is actually a Composio integration ID —
            # fetch the IntegrationModel and pass it directly so the SDK
            # reuses it instead of creating a new integration each time.
            integration = await asyncio.to_thread(
                self._toolset.client.integrations.get,
                id=auth_config_id,
            )
            connection_request = await asyncio.to_thread(
                entity.initiate_connection,
                app_name=app_name,
                integration=integration,
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
