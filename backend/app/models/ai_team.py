"""Models for the multi-AI orchestration team (Claude / Codex / Gemini)."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class AIProvider(str, Enum):
    claude = "claude"
    codex = "codex"
    gemini = "gemini"
    mistral = "mistral"


class TaskType(str, Enum):
    reasoning = "reasoning"        # Complex analysis, logic → Claude
    code_generation = "code_generation"  # Code tasks → Codex
    multimodal = "multimodal"      # Image/video/search → Gemini
    summarization = "summarization"  # Text summarization → any
    workflow_gen = "workflow_gen"   # Workflow JSON generation → Mistral (fine-tuned)
    general = "general"            # General purpose → routed by strategy


class OrchestrationStrategy(str, Enum):
    route = "route"           # Route to best provider for task type
    consensus = "consensus"   # Query multiple, synthesize results
    fallback = "fallback"     # Try providers in priority order
    parallel = "parallel"     # Query all in parallel, return fastest


# Default routing: which provider handles which task type
TASK_ROUTING = {
    TaskType.reasoning: [AIProvider.claude, AIProvider.gemini, AIProvider.codex],
    TaskType.code_generation: [AIProvider.codex, AIProvider.claude, AIProvider.gemini],
    TaskType.multimodal: [AIProvider.gemini, AIProvider.claude, AIProvider.codex],
    TaskType.summarization: [AIProvider.claude, AIProvider.gemini, AIProvider.codex],
    TaskType.workflow_gen: [AIProvider.mistral, AIProvider.claude, AIProvider.codex],
    TaskType.general: [AIProvider.claude, AIProvider.codex, AIProvider.gemini],
}


class TeamTaskRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    task_type: TaskType = TaskType.general
    strategy: OrchestrationStrategy = OrchestrationStrategy.route
    preferred_provider: Optional[AIProvider] = None
    context: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    session_id: str = Field(default_factory=lambda: str(uuid4()))


class ProviderResult(BaseModel):
    provider: AIProvider
    content: str
    latency_ms: float
    token_usage: dict[str, int] = Field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


class TeamTaskResponse(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    strategy_used: OrchestrationStrategy
    task_type: TaskType
    final_result: str
    provider_results: list[ProviderResult]
    primary_provider: AIProvider
    created_at: datetime = Field(default_factory=_utcnow)


class ProviderHealth(BaseModel):
    provider: AIProvider
    available: bool
    last_check: datetime = Field(default_factory=_utcnow)
    avg_latency_ms: Optional[float] = None
    error_rate: float = 0.0


class TeamStatus(BaseModel):
    providers: list[ProviderHealth]
    active_strategy: OrchestrationStrategy
    total_requests: int = 0
    requests_by_provider: dict[str, int] = Field(default_factory=dict)
