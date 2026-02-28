import logging
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


APPEARANCE_STAGES = {
    1: "egg",
    3: "hatchling",
    5: "creature",
    7: "evolved",
    10: "master",
}

ACTION_TO_BRANCH = {
    # Communication
    "send_email": SkillBranch.communication,
    "list_emails": SkillBranch.communication,
    "send_message": SkillBranch.communication,
    "send_slack_message": SkillBranch.communication,
    "post_social": SkillBranch.communication,
    "slack_notify": SkillBranch.communication,
    "discord_message": SkillBranch.communication,
    # Data
    "query_database": SkillBranch.data,
    "fetch_data": SkillBranch.data,
    "transform_data": SkillBranch.data,
    "aggregate_data": SkillBranch.data,
    # Creative
    "generate_image": SkillBranch.creative,
    "create_content": SkillBranch.creative,
    "write_document": SkillBranch.creative,
    # Scheduling
    "create_calendar_event": SkillBranch.scheduling,
    "schedule_task": SkillBranch.scheduling,
    "delay_step": SkillBranch.scheduling,
    "cron_schedule": SkillBranch.scheduling,
    # DevOps
    "deploy_service": SkillBranch.devops,
    "monitor_system": SkillBranch.devops,
    "configure_pipeline": SkillBranch.devops,
    # Task management
    "create_task": SkillBranch.data,
}


class CharacterService:
    def __init__(self):
        self.state = create_default_character()

    @property
    def character_state(self) -> CharacterState:
        return self.state

    def award_xp(self, workflow: WorkflowDefinition) -> dict:
        xp_earned = calculate_xp(workflow)
        self.state.xp += xp_earned

        touched_branches = self._get_workflow_branches(workflow)
        for branch in touched_branches:
            if branch in self.state.skills:
                self.state.skills[branch].xp += xp_earned
                self._check_skill_level_up(branch)

        leveled_up = self._check_level_up()

        for branch in touched_branches:
            if branch in self.state.skills:
                self.state.skills[branch].workflows_completed += 1
        if not touched_branches:
            self.state.skills[SkillBranch.communication].workflows_completed += 1

        achievements_unlocked = self._check_achievements()

        skill_ups = [
            branch.value for branch in touched_branches
            if self.state.skills[branch].level > 0
        ]

        return {
            "xp_earned": xp_earned,
            "level_up": leveled_up,
            "new_level": self.state.level,
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

    def _check_skill_level_up(self, branch: SkillBranch) -> bool:
        skill = self.state.skills[branch]
        xp_required = LEVEL_UP_THRESHOLDS.get(skill.level + 1, skill.level * 500 + 500)

        if skill.xp >= xp_required:
            skill.level += 1
            skill.xp = 0
            return True

        return False

    def _check_level_up(self) -> bool:
        if self.state.level in LEVEL_UP_THRESHOLDS:
            xp_required = LEVEL_UP_THRESHOLDS[self.state.level]
        else:
            xp_required = self.state.level * 500

        if self.state.xp >= xp_required:
            self.state.level += 1
            self.state.xp = 0

            next_level = self.state.level
            if next_level in LEVEL_UP_THRESHOLDS:
                self.state.xp_to_next = LEVEL_UP_THRESHOLDS[next_level]
            else:
                self.state.xp_to_next = next_level * 500

            self._update_appearance_stage()
            self._update_voice_config()

            return True

        return False

    def _update_appearance_stage(self) -> None:
        level = self.state.level
        for stage_level in sorted(APPEARANCE_STAGES.keys(), reverse=True):
            if level >= stage_level:
                self.state.appearance_stage = APPEARANCE_STAGES[stage_level]
                break

    def _update_voice_config(self) -> None:
        from app.services.voice import VoiceService
        self.state.voice_config = VoiceService.get_voice_for_level(self.state.level)

    def _check_achievements(self) -> list[str]:
        unlocked = []
        total_workflows = sum(
            skill.workflows_completed for skill in self.state.skills.values()
        )

        for achievement in self.state.achievements:
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

            elif achievement.id == "multi_service" and self._check_multi_service():
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

            elif achievement.id == "speedrunner" and self._check_speedrunner():
                achievement.earned = True
                achievement.earned_at = datetime.now(tz=UTC)
                unlocked.append(achievement.id)

        return unlocked

    def _check_multi_service(self) -> bool:
        return any(
            skill.workflows_completed >= 3 for skill in self.state.skills.values()
        )

    def _check_speedrunner(self) -> bool:
        return self.state.level >= 5
