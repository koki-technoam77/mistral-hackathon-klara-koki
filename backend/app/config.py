import re
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mistral_api_key: str = ""
    elevenlabs_api_key: str = ""
    composio_api_key: str = ""
    wandb_api_key: str = ""
    wandb_project: str = "kotoflow"
    ft_model_name: Optional[str] = None
    kotoflow_api_key: str = ""

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

    cors_origins: list[str] = ["http://localhost:3000", "https://localhost:3000"]
    allowed_domains: list[str] = [
        "api.mistral.ai",
        "api.elevenlabs.io",
        "api.composio.dev",
        "api.wandb.ai",
        "api.anthropic.com",
        "api.openai.com",
        "generativelanguage.googleapis.com",
    ]

    @field_validator("ft_model_name")
    @classmethod
    def validate_ft_model_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_.:\-/]{1,128}$", v):
            raise ValueError(f"Invalid model name: {v!r}")
        return v

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("Wildcard '*' is not allowed in cors_origins with credentials")
        return v

    model_config = {"env_file": ".env"}
