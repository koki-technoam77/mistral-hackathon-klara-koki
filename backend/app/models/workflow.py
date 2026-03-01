import re
from datetime import UTC, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)

from pydantic import BaseModel, Field, field_validator


class TriggerType(str, Enum):
    schedule = "schedule"
    webhook = "webhook"
    manual = "manual"


class WorkflowTrigger(BaseModel):
    type: TriggerType
    cron: Optional[str] = Field(None, pattern=r"^(\S+ ){4}\S+$")
    webhook_url: Optional[str] = None

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("https://"):
            raise ValueError("webhook_url must use HTTPS")
        if len(v) > 2048:
            raise ValueError("webhook_url too long")
        return v


ALLOWED_ACTIONS = frozenset([
    "api_call",
    "browser_action",
    "llm_summarize",
    "web_search",
    "send_email",
    "create_calendar_event",
    "list_emails",
    "create_task",
    "send_slack_message",
    "post_social",
    "send_message",
    "slack_notify",
    "discord_message",
    "query_database",
    "fetch_data",
    "transform_data",
    "aggregate_data",
    "generate_image",
    "create_content",
    "write_document",
    "schedule_task",
    "delay_step",
    "cron_schedule",
    "deploy_service",
    "monitor_system",
    "configure_pipeline",
    # Google Sheets (Composio, OAuth)
    "sheets_create_row",
    "sheets_query",
    "sheets_lookup_row",
    "sheets_get_schema",
    # LinkedIn (Composio, OAuth)
    "linkedin_create_post",
    "linkedin_share_url",
    "linkedin_get_my_info",
    # Twitter / X (Composio, OAuth)
    "tweet",
    "twitter_search",
    "twitter_get_analytics",
    # GitHub (Composio, OAuth)
    "github_create_issue",
    "github_create_pr",
    "github_star_repo",
    "github_list_repos",
    # Hacker News (Composio, no auth)
    "hackernews_frontpage",
    "hackernews_get_item",
    "hackernews_latest",
    "hackernews_today",
    "hackernews_get_user",
])


class WorkflowStep(BaseModel):
    id: str = Field(..., pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    action: str = Field(..., pattern=r"^[a-zA-Z0-9_]{1,64}$")
    params: dict = Field(default_factory=dict)
    output: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_]{1,64}$")
    depends_on: Optional[list[str]] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ALLOWED_ACTIONS:
            raise ValueError(f"Unknown action: {v!r}")
        return v


class WorkflowDefinition(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    trigger: WorkflowTrigger
    steps: list[WorkflowStep]

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[WorkflowStep]) -> list[WorkflowStep]:
        if len(v) > 10:
            raise ValueError("Workflow cannot have more than 10 steps")
        if len(v) == 0:
            raise ValueError("Workflow must have at least one step")
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Step IDs must be unique")
        id_set = set(ids)
        for step in v:
            if step.depends_on:
                for dep in step.depends_on:
                    if dep not in id_set:
                        raise ValueError(f"Step {step.id!r} depends on unknown step {dep!r}")
        # Cycle detection
        graph = {s.id: set(s.depends_on or []) for s in v}
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for node in graph:
            if node not in visited:
                if has_cycle(node):
                    raise ValueError("Workflow steps contain a dependency cycle")
        return v


class WorkflowExecutionStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class WorkflowExecution(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workflow: WorkflowDefinition
    status: WorkflowExecutionStatus = WorkflowExecutionStatus.pending
    step_results: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=_utcnow)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("role must be one of: user, assistant, system")
        return v
