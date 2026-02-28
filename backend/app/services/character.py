import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime

from app.models.character import (
    CharacterState,
    SkillBranch,
    SkillState,
    VoiceConfig,
    Achievement,
    calculate_xp,
    create_default_character,
    LEVEL_UP_THRESHOLDS,
)
from app.models.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


APPEARANCE_STAGES = {
    1: "egg",
    3: "hatchling",
    5: "creature",
    7: "evolved",
    10: "master",
}

ACTION_TO_BRANCH = {
    "send_email": SkillBranch.communication,
    "send_message": SkillBranch.communication,
    "post_social": SkillBranch.communication,
    "slack_notify": SkillBranch.communication,
    "discord_message": SkillBranch.communication,
    "query_database": SkillBranch.data,
    "fetch_data": SkillBranch.data,
    "transform_data": SkillBranch.data,
    "aggregate_data": SkillBranch.data,
    "generate_image": SkillBranch.creative,
    "create_content": SkillBranch.creative,
    "write_document": SkillBranch.creative,
    "schedule_task": SkillBranch.scheduling,
    "delay_step": SkillBranch.scheduling,
    "cron_schedule": SkillBranch.scheduling,
    "deploy_service": SkillBranch.devops,
    "monitor_system": SkillBranch.devops,
    "configure_pipeline": SkillBranch.devops,
}


class CharacterService:
    def __init__(self, storage_dir=None):
        self._states: dict[str, CharacterState] = {}
        self._storage_dir = storage_dir
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)

    def get_state(self, session_id: str = "default") -> CharacterState:
        if session_id not in self._states:
            self._states[session_id] = self._load_or_create(session_id)
        return self._states[session_id]

    @property
    def state(self) -> CharacterState:
        return self.get_state("default")

    @property
    def character_state(self) -> CharacterState:
        return self.get_state("default")

    def award_xp(self, workflow: WorkflowDefinition, session_id: str = "default") -> dict:
        state = self.get_state(session_id)
        xp_earned = calculate_xp(workflow)
        state.xp += xp_earned

        touched_branches = self._get_workflow_branches(workflow)
        for branch in touched_branches:
            if branch in state.skills:
                state.skills[branch].xp += xp_earned
                self._check_skill_level_up(state, branch)

        leveled_up = self._check_level_up(state)

        for branch in touched_branches:
            if branch in state.skills:
                state.skills[branch].workflows_completed += 1
        if not touched_branches:
            state.skills[SkillBranch.communication].workflows_completed += 1

        achievements_unlocked = self._check_achievements(state)

        skill_ups = [
            branch.value for branch in touched_branches
            if state.skills[branch].level > 0
        ]

        self._persist(session_id, state)

        return {
            "xp_earned": xp_earned,
            "level_up": leveled_up,
            "new_level": state.level,
            "achievements_unlocked": achievements_unlocked,
            "skill_ups": skill_ups,
        }

    def _get_workflow_branches(self, workflow: WorkflowDefinition) -> set[SkillBranch]:
        branches = set()
        for step in workflow.steps:
            branch = ACTION_TO_BRANCH.get(step.action)
            if branch:
                branches.add(branch)
        return branches

    def _check_skill_level_up(self, state: CharacterState, branch: SkillBranch) -> bool:
        skill = state.skills[branch]
        xp_required = LEVEL_UP_THRESHOLDS.get(skill.level + 1, skill.level * 500 + 500)

        if skill.xp >= xp_required:
            skill.level += 1
            skill.xp = 0
            return True

        return False

    def _check_level_up(self, state: CharacterState) -> bool:
        if state.level in LEVEL_UP_THRESHOLDS:
            xp_required = LEVEL_UP_THRESHOLDS[state.level]
        else:
            xp_required = state.level * 500

        if state.xp >= xp_required:
            state.level += 1
            state.xp = 0

            next_level = state.level
            if next_level in LEVEL_UP_THRESHOLDS:
                state.xp_to_next = LEVEL_UP_THRESHOLDS[next_level]
            else:
                state.xp_to_next = next_level * 500

            self._update_appearance_stage(state)
            self._update_voice_config(state)

            return True

        return False

    def _update_appearance_stage(self, state: CharacterState) -> None:
        level = state.level
        for stage_level in sorted(APPEARANCE_STAGES.keys(), reverse=True):
            if level >= stage_level:
                state.appearance_stage = APPEARANCE_STAGES[stage_level]
                break

    def _update_voice_config(self, state: CharacterState) -> None:
        from app.services.voice import VoiceService
        state.voice_config = VoiceService.get_voice_for_level(state.level)

    def _check_achievements(self, state: CharacterState) -> list[str]:
        unlocked = []
        total_workflows = sum(
            skill.workflows_completed for skill in state.skills.values()
        )

        for achievement in state.achievements:
            if achievement.earned:
                continue

            if achievement.id == "first_workflow" and total_workflows >= 1:
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

            elif achievement.id == "ten_workflows" and total_workflows >= 10:
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

            elif achievement.id == "multi_service" and self._check_multi_service(state):
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

            elif achievement.id == "speedrunner" and self._check_speedrunner(state):
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

        return unlocked

    def _check_multi_service(self, state: CharacterState) -> bool:
        return any(
            skill.workflows_completed >= 3 for skill in state.skills.values()
        )

    def _check_speedrunner(self, state: CharacterState) -> bool:
        return state.level >= 5

    # ── Persistence helpers ──────────────────────────────────────────────────

    def _safe_id(self, session_id: str) -> str:
        if _SAFE_ID_RE.match(session_id):
            return session_id
        return hashlib.sha256(session_id.encode()).hexdigest()[:16]

    def _path_for(self, session_id: str) -> str:
        if not self._storage_dir:
            return ""
        return os.path.join(self._storage_dir, f"{self._safe_id(session_id)}.json")

    def _load_or_create(self, session_id: str) -> CharacterState:
        if not self._storage_dir:
            return create_default_character()
        path = self._path_for(session_id)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                return CharacterState.model_validate(data)
            except Exception:
                logger.warning("Failed to load character state for %s", session_id, exc_info=True)
        return create_default_character()

    def _persist(self, session_id: str, state: CharacterState) -> None:
        if not self._storage_dir:
            return
        path = self._path_for(session_id)
        try:
            with open(path, "w") as f:
                json.dump(state.model_dump(mode="json"), f)
        except Exception:
            logger.warning("Failed to persist character state for %s", session_id, exc_info=True)
