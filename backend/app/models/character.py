from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .workflow import WorkflowDefinition


class SkillBranch(str, Enum):
    communication = "communication"
    data = "data"
    creative = "creative"
    scheduling = "scheduling"
    devops = "devops"


class SkillState(BaseModel):
    level: int = 0
    workflows_completed: int = 0
    xp: int = 0


class Achievement(BaseModel):
    id: str
    name: str
    icon: str
    description: str
    earned: bool = False
    earned_at: Optional[datetime] = None


class VoiceConfig(BaseModel):
    voice_id: str
    stability: float
    style: float


class CharacterState(BaseModel):
    name: str = "Flow-chan"
    level: int = 1
    xp: int = 0
    xp_to_next: int = 500
    appearance_stage: str = "egg"
    voice_config: VoiceConfig
    skills: dict[SkillBranch, SkillState] = Field(default_factory=dict)
    achievements: list[Achievement] = Field(default_factory=list)


LEVEL_UP_THRESHOLDS = {
    1: 500,
    2: 1000,
    3: 2000,
    4: 3500,
    5: 5000,
}


DEFAULT_ACHIEVEMENTS = [
    Achievement(
        id="first_workflow",
        name="Workflow Architect",
        icon="🏗️",
        description="Complete your first workflow",
    ),
    Achievement(
        id="ten_workflows",
        name="Automation Master",
        icon="🤖",
        description="Complete 10 workflows",
    ),
    Achievement(
        id="multi_service",
        name="Integration Expert",
        icon="🔗",
        description="Use 5 different services in a single workflow",
    ),
    Achievement(
        id="speedrunner",
        name="Lightning Fast",
        icon="⚡",
        description="Complete a workflow in under 30 seconds",
    ),
]


def create_default_character(voice_id: str = "EXAVITQu4vr4xnSDxMaL", stability: float = 0.85, style: float = 0.3) -> CharacterState:
    return CharacterState(
        voice_config=VoiceConfig(voice_id=voice_id, stability=stability, style=style),
        skills={branch: SkillState() for branch in SkillBranch},
        achievements=[ach.model_copy() for ach in DEFAULT_ACHIEVEMENTS],
    )


def calculate_xp(workflow: WorkflowDefinition) -> int:
    base_xp = 100
    step_bonus = len(workflow.steps) * 50

    unique_actions = len(set(step.action for step in workflow.steps))
    service_diversity = unique_actions * 75

    complexity_bonus = 0
    if len(workflow.steps) > 5:
        complexity_bonus = 200
    elif len(workflow.steps) > 3:
        complexity_bonus = 100

    return base_xp + step_bonus + service_diversity + complexity_bonus
