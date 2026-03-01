import json
import re
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


def _parse_str_list(v: object, default: list[str]) -> list[str]:
    """Parse a list field that may come as JSON array, comma-separated string, or list."""
    if isinstance(v, list):
        return v
    if not isinstance(v, str) or not v.strip():
        return default
    # Try JSON array first
    try:
        parsed = json.loads(v)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to comma-separated
    return [item.strip() for item in v.split(",") if item.strip()]


class Settings(BaseSettings):
    mistral_api_key: str = ""
    elevenlabs_api_key: str = ""
    composio_api_key: str = ""
    wandb_api_key: str = ""
    wandb_project: str = "kotoflow"
    ft_model_name: Optional[str] = None
    kotoflow_api_key: str = ""

    # Anam AI Avatar Settings
    anam_api_key: str = ""
    anam_avatar_id: str = ""

    # ElevenLabs Conversational AI Agent
    elevenlabs_agent_id: str = ""

    # Character persistence
    character_storage_dir: str = "/tmp/kotoflow_characters"

    # Multi-AI Provider OAuth Settings
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # OAuth Token Endpoints (subscription-based)
    anthropic_oauth_client_id: str = ""
    anthropic_oauth_client_secret: str = ""
    openai_oauth_client_id: str = ""
    openai_oauth_client_secret: str = ""
    gemini_oauth_client_id: str = ""
    gemini_oauth_client_secret: str = ""

    # AI Team Configuration
    ai_team_default_strategy: str = "route"  # route | consensus | fallback
    ai_team_consensus_threshold: int = 2     # min providers for consensus

    # Accept JSON array, comma-separated string, or Python list
    cors_origins: str = "http://localhost:3000,https://localhost:3000"
    allowed_domains: str = "api.mistral.ai,api.elevenlabs.io,api.composio.dev,api.wandb.ai,api.anthropic.com,api.openai.com,generativelanguage.googleapis.com,api.anam.ai"

    @field_validator("ft_model_name")
    @classmethod
    def validate_ft_model_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_.:\-/]{1,128}$", v):
            raise ValueError(f"Invalid model name: {v!r}")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        origins = _parse_str_list(self.cors_origins, ["http://localhost:3000"])
        if "*" in origins:
            raise ValueError("Wildcard '*' is not allowed in cors_origins with credentials")
        return origins

    @property
    def allowed_domains_list(self) -> list[str]:
        return _parse_str_list(self.allowed_domains, ["api.mistral.ai"])

    model_config = {"env_file": ".env"}
