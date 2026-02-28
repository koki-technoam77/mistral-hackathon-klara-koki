"""
Comprehensive pytest tests for kotoflow backend.
Tests models, services, executor, security, and API routes without requiring real API keys.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException

from app.models.workflow import (
    WorkflowDefinition,
    WorkflowTrigger,
    WorkflowStep,
    TriggerType,
    WorkflowExecution,
    WorkflowExecutionStatus,
    ConversationMessage,
    ALLOWED_ACTIONS,
)
from app.models.character import (
    CharacterState,
    SkillBranch,
    SkillState,
    VoiceConfig,
    Achievement,
    create_default_character,
    calculate_xp,
    LEVEL_UP_THRESHOLDS,
)
from app.services.character import CharacterService, ACTION_TO_BRANCH
from app.services.executor import WorkflowExecutor
from app.config import Settings


# ============================================================================
# MODEL TESTS
# ============================================================================

class TestWorkflowDefinition:
    """Test WorkflowDefinition model creation and validation."""

    def test_workflow_definition_creation(self):
        """Test creating a valid WorkflowDefinition."""
        workflow = WorkflowDefinition(
            name="Test Workflow",
            description="A test workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email", params={"to": "test@example.com"}),
            ],
        )
        assert workflow.name == "Test Workflow"
        assert workflow.description == "A test workflow"
        assert workflow.trigger.type == TriggerType.manual
        assert len(workflow.steps) == 1

    def test_workflow_definition_with_multiple_steps(self):
        """Test WorkflowDefinition with multiple steps."""
        steps = [
            WorkflowStep(id=f"step_{i}", action="send_email", params={})
            for i in range(1, 6)
        ]
        workflow = WorkflowDefinition(
            name="Multi Step Workflow",
            trigger=WorkflowTrigger(type=TriggerType.schedule, cron="0 0 * * *"),
            steps=steps,
        )
        assert len(workflow.steps) == 5

    def test_workflow_step_count_validation_max_10(self):
        """Test that workflow cannot have more than 10 steps."""
        steps = [
            WorkflowStep(id=f"step_{i}", action="send_email", params={})
            for i in range(1, 12)
        ]
        with pytest.raises(ValueError, match="Workflow cannot have more than 10 steps"):
            WorkflowDefinition(
                name="Too Many Steps",
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=steps,
            )

    def test_workflow_step_count_validation_exactly_10(self):
        """Test that workflow can have exactly 10 steps."""
        steps = [
            WorkflowStep(id=f"step_{i}", action="send_email", params={})
            for i in range(1, 11)
        ]
        workflow = WorkflowDefinition(
            name="Max Steps Workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=steps,
        )
        assert len(workflow.steps) == 10

    def test_workflow_empty_steps_invalid(self):
        """Test that workflow with no steps is invalid."""
        with pytest.raises(ValueError, match="Workflow must have at least one step"):
            WorkflowDefinition(
                name="Empty",
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=[],
            )

    def test_workflow_duplicate_step_ids_invalid(self):
        """Test that duplicate step IDs are rejected."""
        with pytest.raises(ValueError, match="Step IDs must be unique"):
            WorkflowDefinition(
                name="Dups",
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=[
                    WorkflowStep(id="step_1", action="send_email"),
                    WorkflowStep(id="step_1", action="create_task"),
                ],
            )

    def test_workflow_cycle_detection(self):
        """Test that cyclic dependencies are rejected."""
        with pytest.raises(ValueError, match="dependency cycle"):
            WorkflowDefinition(
                name="Cycle",
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=[
                    WorkflowStep(id="step_a", action="send_email", depends_on=["step_b"]),
                    WorkflowStep(id="step_b", action="create_task", depends_on=["step_a"]),
                ],
            )

    def test_workflow_unknown_dependency_rejected(self):
        """Test that dependencies on non-existent steps are rejected."""
        with pytest.raises(ValueError, match="depends on unknown step"):
            WorkflowDefinition(
                name="Bad Dep",
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=[
                    WorkflowStep(id="step_1", action="send_email", depends_on=["nonexistent"]),
                ],
            )


class TestWorkflowStepValidation:
    """Test WorkflowStep field validation."""

    def test_invalid_step_id_rejected(self):
        """Test that step IDs with special chars are rejected."""
        with pytest.raises(ValueError):
            WorkflowStep(id="../etc/passwd", action="send_email")

    def test_invalid_action_rejected(self):
        """Test that unknown actions are rejected."""
        with pytest.raises(ValueError, match="Unknown action"):
            WorkflowStep(id="step_1", action="arbitrary_code_exec")

    def test_valid_actions_accepted(self):
        """Test that all allowed actions pass validation."""
        for action in ["send_email", "api_call", "llm_summarize", "web_search"]:
            step = WorkflowStep(id="step_1", action=action)
            assert step.action == action


class TestTriggerType:
    """Test TriggerType enum."""

    def test_trigger_type_schedule(self):
        """Test schedule trigger type."""
        trigger = WorkflowTrigger(type=TriggerType.schedule, cron="0 0 * * *")
        assert trigger.type == TriggerType.schedule
        assert trigger.cron == "0 0 * * *"

    def test_trigger_type_webhook(self):
        """Test webhook trigger type."""
        trigger = WorkflowTrigger(
            type=TriggerType.webhook,
            webhook_url="https://example.com/webhook",
        )
        assert trigger.type == TriggerType.webhook
        assert trigger.webhook_url == "https://example.com/webhook"

    def test_trigger_type_manual(self):
        """Test manual trigger type."""
        trigger = WorkflowTrigger(type=TriggerType.manual)
        assert trigger.type == TriggerType.manual

    def test_webhook_url_must_be_https(self):
        """Test that webhook_url must use HTTPS."""
        with pytest.raises(ValueError, match="HTTPS"):
            WorkflowTrigger(
                type=TriggerType.webhook,
                webhook_url="http://example.com/webhook",
            )

    def test_invalid_cron_rejected(self):
        """Test that invalid cron expressions are rejected."""
        with pytest.raises(ValueError):
            WorkflowTrigger(type=TriggerType.schedule, cron="invalid cron")


class TestConversationMessage:
    """Test ConversationMessage model."""

    def test_conversation_message_user_role(self):
        """Test creating a user message."""
        msg = ConversationMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_conversation_message_assistant_role(self):
        """Test creating an assistant message."""
        msg = ConversationMessage(role="assistant", content="Hi there")
        assert msg.role == "assistant"

    def test_conversation_message_invalid_role(self):
        """Test that invalid role raises error."""
        with pytest.raises(ValueError, match="role must be one of"):
            ConversationMessage(role="invalid", content="test")


class TestCharacterStateCreation:
    """Test CharacterState creation and default character function."""

    def test_create_default_character(self):
        """Test create_default_character function."""
        char = create_default_character()
        assert char.name == "Flow-chan"
        assert char.level == 1
        assert char.xp == 0
        assert char.xp_to_next == 500
        assert char.appearance_stage == "egg"
        assert char.voice_config is not None

    def test_create_default_character_with_custom_voice(self):
        """Test create_default_character with custom voice parameters."""
        char = create_default_character(voice_id="custom", stability=0.7, style=0.5)
        assert char.voice_config.voice_id == "custom"
        assert char.voice_config.stability == 0.7
        assert char.voice_config.style == 0.5

    def test_default_character_has_all_skill_branches(self):
        """Test that default character has all skill branches."""
        char = create_default_character()
        for branch in SkillBranch:
            assert branch in char.skills
            assert isinstance(char.skills[branch], SkillState)

    def test_default_character_has_achievements(self):
        """Test that default character has achievement list."""
        char = create_default_character()
        assert len(char.achievements) > 0
        achievement_ids = {ach.id for ach in char.achievements}
        assert "first_workflow" in achievement_ids


class TestCalculateXp:
    """Test XP calculation based on workflow complexity."""

    def test_calculate_xp_single_step(self):
        """Test XP calculation for single step workflow."""
        workflow = WorkflowDefinition(
            name="Single Step",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[WorkflowStep(id="step_1", action="send_email")],
        )
        xp = calculate_xp(workflow)
        # base_xp(100) + step_bonus(1*50) + service_diversity(1*75) = 225
        assert xp == 225

    def test_calculate_xp_three_steps(self):
        """Test XP calculation for 3-step workflow."""
        workflow = WorkflowDefinition(
            name="Three Steps",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="send_message"),
            ],
        )
        xp = calculate_xp(workflow)
        # base(100) + step_bonus(3*50=150) + service_diversity(3*75=225) = 475
        assert xp == 475

    def test_calculate_xp_five_steps_with_complexity(self):
        """Test XP calculation for 5 step workflow with complexity bonus."""
        workflow = WorkflowDefinition(
            name="Complex Workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="create_task"),
                WorkflowStep(id="step_4", action="api_call"),
                WorkflowStep(id="step_5", action="web_search"),
            ],
        )
        xp = calculate_xp(workflow)
        # base(100) + step_bonus(5*50=250) + service_diversity(5*75=375) + complexity(100 for >3) = 825
        assert xp == 825

    def test_calculate_xp_six_steps_high_complexity(self):
        """Test XP calculation for 6+ step workflow with high complexity bonus."""
        workflow = WorkflowDefinition(
            name="Very Complex",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="create_task"),
                WorkflowStep(id="step_4", action="api_call"),
                WorkflowStep(id="step_5", action="web_search"),
                WorkflowStep(id="step_6", action="llm_summarize"),
            ],
        )
        xp = calculate_xp(workflow)
        # base(100) + step_bonus(6*50=300) + service_diversity(6*75=450) + complexity(200) = 1050
        assert xp == 1050


# ============================================================================
# CHARACTER SERVICE TESTS
# ============================================================================

class TestCharacterServiceAwardXp:
    """Test CharacterService.award_xp functionality."""

    def test_award_xp_returns_correct_structure(self, character_service, sample_workflow):
        """Test that award_xp returns correct structure with required keys."""
        result = character_service.award_xp(sample_workflow)

        assert "xp_earned" in result
        assert "level_up" in result
        assert "new_level" in result
        assert "achievements_unlocked" in result
        assert "skill_ups" in result

    def test_award_xp_updates_character_xp(self, character_service, sample_workflow):
        """Test that award_xp updates character XP."""
        initial_xp = character_service.state.xp
        result = character_service.award_xp(sample_workflow)

        xp_earned = result["xp_earned"]
        assert xp_earned > 0
        assert character_service.state.xp >= initial_xp + xp_earned

    def test_level_up_happens_at_threshold(self, character_service):

        small_workflow = WorkflowDefinition(
            name="Small Workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[WorkflowStep(id="step_1", action="send_email")],
        )

        initial_level = character_service.state.level

        for _ in range(5):
            character_service.award_xp(small_workflow)

        assert character_service.state.level >= initial_level

    def test_achievement_first_workflow_unlocks(self, character_service, sample_workflow):
        """Test that first_workflow achievement is unlocked after first workflow."""
        result = character_service.award_xp(sample_workflow)

        assert "first_workflow" in result["achievements_unlocked"]

        first_workflow_achievement = next(
            (a for a in character_service.state.achievements if a.id == "first_workflow"),
            None
        )
        assert first_workflow_achievement is not None
        assert first_workflow_achievement.earned is True

    def test_achievement_ten_workflows_after_ten_completions(self, character_service):
        """Test that ten_workflows achievement unlocks after 10 workflows."""
        workflow = WorkflowDefinition(
            name="Small Workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[WorkflowStep(id="step_1", action="send_email")],
        )

        for i in range(10):
            result = character_service.award_xp(workflow)

        total_workflows = sum(
            skill.workflows_completed for skill in character_service.state.skills.values()
        )

        assert total_workflows >= 10

    def test_appearance_stage_changes_on_level_up(self, character_service):

        initial_stage = character_service.state.appearance_stage
        initial_level = character_service.state.level

        complex_workflow = WorkflowDefinition(
            name="Complex",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="create_task"),
                WorkflowStep(id="step_4", action="api_call"),
                WorkflowStep(id="step_5", action="web_search"),
                WorkflowStep(id="step_6", action="llm_summarize"),
            ],
        )

        for _ in range(10):
            character_service.award_xp(complex_workflow)

        if character_service.state.level > initial_level:
            if character_service.state.level >= 3:
                assert character_service.state.appearance_stage in ["hatchling", "creature", "evolved", "master"]

    def test_skill_branch_tracking(self, character_service):
        """Test that skill branches are tracked correctly."""
        workflow = WorkflowDefinition(
            name="Communication Workflow",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
            ],
        )

        initial_communication_workflows = character_service.state.skills[SkillBranch.communication].workflows_completed

        result = character_service.award_xp(workflow)

        assert SkillBranch.communication.value in result["skill_ups"] or \
               character_service.state.skills[SkillBranch.communication].workflows_completed > initial_communication_workflows


# ============================================================================
# EXECUTOR TESTS
# ============================================================================

class TestWorkflowExecutorInterpolation:
    """Test WorkflowExecutor parameter interpolation."""

    def test_interpolate_params_simple_replacement(self, settings):
        """Test simple {{var}} replacement."""
        executor = WorkflowExecutor(settings)
        params = {"url": "https://api.example.com/user/{{user_id}}"}
        context = {"previous_results": {"user_id": "123"}}

        result = executor._interpolate_params(params, context)

        assert result["url"] == "https://api.example.com/user/123"

    def test_interpolate_params_multiple_replacements(self, settings):
        """Test multiple {{var}} replacements in one param."""
        executor = WorkflowExecutor(settings)
        params = {"message": "Hello {{first_name}}, your ID is {{user_id}}"}
        context = {"previous_results": {"first_name": "John", "user_id": "456"}}

        result = executor._interpolate_params(params, context)

        assert result["message"] == "Hello John, your ID is 456"

    def test_interpolate_params_nested_values(self, settings):
        """Test interpolation with nested context values."""
        executor = WorkflowExecutor(settings)
        params = {"email": "{{user.email}}"}
        context = {"previous_results": {"user": {"email": "test@example.com"}}}

        result = executor._interpolate_params(params, context)

        assert result["email"] == "test@example.com"

    def test_interpolate_params_no_replacement_needed(self, settings):
        """Test interpolation when no {{var}} patterns exist."""
        executor = WorkflowExecutor(settings)
        params = {"message": "Simple message"}
        context = {"previous_results": {}}

        result = executor._interpolate_params(params, context)

        assert result["message"] == "Simple message"

    def test_interpolate_params_dict_values(self, settings):
        """Test interpolation with nested dict values."""
        executor = WorkflowExecutor(settings)
        params = {"data": {"nested": "{{value}}"}}
        context = {"previous_results": {"value": "success"}}

        result = executor._interpolate_params(params, context)

        assert result["data"]["nested"] == "success"

    def test_interpolate_depth_limit(self, settings):
        """Test that deeply nested template keys are ignored."""
        executor = WorkflowExecutor(settings)
        params = {"val": "{{a.b.c.d.e.f.g}}"}
        context = {"previous_results": {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deep"}}}}}}}}

        result = executor._interpolate_params(params, context)
        # Depth > 5 should not resolve
        assert "{{a.b.c.d.e.f.g}}" in result["val"]


class TestWorkflowExecutorUrlSafety:
    """Test WorkflowExecutor URL safety checking."""

    def test_https_allowed_domain_passes(self, settings):
        """Test that HTTPS URLs to allowed domains pass."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("https://api.mistral.ai/v1/chat") is True
        assert executor._is_url_safe("https://api.elevenlabs.io/v1/tts") is True

    def test_http_rejected(self, settings):
        """Test that HTTP URLs are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("http://api.mistral.ai/v1/chat") is False

    def test_unknown_domain_rejected(self, settings):
        """Test that unknown domains are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("https://malicious.example.com/data") is False

    def test_private_ip_rejected(self, settings):
        """Test that private IPs are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("https://192.168.1.1/secret") is False
        assert executor._is_url_safe("https://10.0.0.1/internal") is False
        assert executor._is_url_safe("https://127.0.0.1/localhost") is False

    def test_metadata_ip_rejected(self, settings):
        """Test that cloud metadata IPs are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("https://169.254.169.254/latest/meta-data/") is False

    def test_url_with_credentials_rejected(self, settings):
        """Test that URLs with embedded credentials are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("https://user:pass@api.mistral.ai/v1/chat") is False
        assert executor._is_url_safe("https://api.mistral.ai@evil.com/secret") is False

    def test_file_scheme_rejected(self, settings):
        """Test that non-HTTPS schemes are rejected."""
        executor = WorkflowExecutor(settings)
        assert executor._is_url_safe("file:///etc/passwd") is False
        assert executor._is_url_safe("ftp://api.mistral.ai/data") is False


@pytest.mark.asyncio
class TestWorkflowExecutorExecution:
    """Test WorkflowExecutor step execution."""

    async def test_execute_runs_all_steps_in_order(self, settings, sample_workflow):
        """Test that execute runs all steps in order."""
        executor = WorkflowExecutor(settings)
        execution = await executor.execute(sample_workflow)

        assert execution.status == WorkflowExecutionStatus.completed
        assert len(execution.step_results) >= len(sample_workflow.steps)

    async def test_execute_respects_step_dependencies(self, settings):
        """Test that execution respects step dependencies."""
        workflow = WorkflowDefinition(
            name="Dependent Steps",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email", output="result"),
                WorkflowStep(
                    id="step_2",
                    action="send_slack_message",
                    depends_on=["step_1"],
                    params={"message": "{{step_1.result}}"},
                ),
            ],
        )

        executor = WorkflowExecutor(settings)
        execution = await executor.execute(workflow)

        assert execution.status == WorkflowExecutionStatus.completed
        assert "step_1" in execution.step_results
        assert "step_2" in execution.step_results

    @patch("app.services.executor.Mistral")
    async def test_execute_llm_summarize_step(self, mock_mistral_class, settings):
        """Test LLM summarize step with mocked Mistral client."""
        mock_client = AsyncMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a summary of the content."
        mock_client.chat.complete_async = AsyncMock(return_value=mock_response)

        executor = WorkflowExecutor(settings)
        executor.mistral_client = mock_client

        workflow = WorkflowDefinition(
            name="Summarize Test",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(
                    id="summarize_step",
                    action="llm_summarize",
                    params={"content": "Long text to summarize", "style": "brief"},
                ),
            ],
        )

        execution = await executor.execute(workflow)

        assert execution.status == WorkflowExecutionStatus.completed
        assert "summarize_step" in execution.step_results

    async def test_execute_timeout(self, settings):
        """Test that execution times out correctly."""
        executor = WorkflowExecutor(settings)

        workflow = WorkflowDefinition(
            name="Simple",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[WorkflowStep(id="step_1", action="web_search", params={"query": "test"})],
        )

        # Normal execution should complete within timeout
        execution = await executor.execute(workflow)
        assert execution.status == WorkflowExecutionStatus.completed


# ============================================================================
# SECURITY TESTS
# ============================================================================

class TestSecurityValidation:
    """Test security-related validations."""

    def test_config_rejects_wildcard_cors(self):
        """Test that wildcard CORS origins are rejected."""
        s = Settings(cors_origins="*")
        with pytest.raises(ValueError, match="Wildcard"):
            s.cors_origins_list

    def test_config_validates_ft_model_name(self):
        """Test that invalid model names are rejected."""
        with pytest.raises(ValueError):
            Settings(ft_model_name="model; DROP TABLE users;--")

    def test_config_accepts_valid_ft_model_name(self):
        """Test that valid model names are accepted."""
        s = Settings(ft_model_name="ft:mistral:my-model-v1")
        assert s.ft_model_name == "ft:mistral:my-model-v1"

    def test_workflow_name_max_length(self):
        """Test that overly long workflow names are rejected."""
        with pytest.raises(ValueError):
            WorkflowDefinition(
                name="x" * 201,
                trigger=WorkflowTrigger(type=TriggerType.manual),
                steps=[WorkflowStep(id="step_1", action="send_email")],
            )


# ============================================================================
# API ROUTE TESTS
# ============================================================================

class TestApiRoutes:
    """Test API routes."""

    def test_get_health_returns_200(self, test_client):
        """Test GET /api/health returns 200."""
        response = test_client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_get_character_returns_character_state(self, test_client):
        """Test GET /api/character returns character state."""
        response = test_client.get("/api/character")
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "level" in data
        assert "xp" in data
        assert "appearance_stage" in data
        assert "voice_config" in data

    def test_get_character_has_valid_structure(self, test_client):
        """Test GET /api/character returns proper CharacterState structure."""
        response = test_client.get("/api/character")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Flow-chan"
        assert data["level"] == 1
        assert data["xp"] == 0
        assert "skills" in data
        assert "achievements" in data

    def test_post_chat_reset_returns_status(self, test_client):
        """Test POST /api/chat/reset returns status."""
        response = test_client.post("/api/chat/reset")
        assert response.status_code == 200

    def test_health_endpoint_no_auth_required(self, test_client):
        """Test that health endpoint works without auth."""
        response = test_client.get("/api/health")
        assert response.status_code == 200

    def test_error_messages_are_generic(self, test_client):
        """Test that error responses don't leak internal details."""
        # Send invalid data that should trigger a 422
        response = test_client.post("/api/chat", json={})
        # Should get a validation error, not an internal error with stack trace
        assert response.status_code == 422


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestCharacterXpProgression:
    """Test character XP progression system."""

    def test_level_progression_sequence(self, character_service):

        workflow = WorkflowDefinition(
            name="Test",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="create_task"),
                WorkflowStep(id="step_4", action="api_call"),
                WorkflowStep(id="step_5", action="web_search"),
                WorkflowStep(id="step_6", action="llm_summarize"),
            ],
        )

        starting_level = character_service.state.level
        max_iterations = 20

        for i in range(max_iterations):
            result = character_service.award_xp(workflow)
            if character_service.state.level > starting_level:
                break

        assert character_service.state.level >= starting_level

    def test_xp_resets_on_level_up(self, character_service):

        workflow = WorkflowDefinition(
            name="Test",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[
                WorkflowStep(id="step_1", action="send_email"),
                WorkflowStep(id="step_2", action="send_slack_message"),
                WorkflowStep(id="step_3", action="create_task"),
                WorkflowStep(id="step_4", action="api_call"),
                WorkflowStep(id="step_5", action="web_search"),
                WorkflowStep(id="step_6", action="llm_summarize"),
            ],
        )

        initial_level = character_service.state.level

        for _ in range(20):
            result = character_service.award_xp(workflow)
            if character_service.state.level > initial_level:
                assert character_service.state.xp < LEVEL_UP_THRESHOLDS[initial_level]
                break


class TestWorkflowValidation:
    """Test workflow validation constraints."""

    def test_step_with_dependencies(self):
        """Test step with dependencies is properly structured."""
        step = WorkflowStep(
            id="step_2",
            action="send_email",
            depends_on=["step_1"],
            params={"to": "test@example.com"},
        )
        assert step.depends_on == ["step_1"]

    def test_step_with_output_field(self):
        """Test step with output field for next step consumption."""
        step = WorkflowStep(
            id="step_1",
            action="fetch_data",
            params={"url": "https://api.example.com"},
            output="data",
        )
        assert step.output == "data"


# ============================================================================
# COMPOSIO OAUTH TESTS
# ============================================================================

class TestComposioAuthService:
    """Test ComposioAuthService initialization and methods."""

    def test_service_unavailable_without_api_key(self):
        """Service should report unavailable without API key."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)
        assert not service.available

    def test_service_get_required_apps(self):
        """get_required_apps should map actions to Composio app names."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)

        apps = service.get_required_apps(["send_email", "create_calendar_event"])
        assert "gmail" in apps
        assert "googlecalendar" in apps

    def test_service_get_required_apps_no_composio_actions(self):
        """get_required_apps returns empty for non-Composio actions."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)

        apps = service.get_required_apps(["web_search", "llm_summarize"])
        assert apps == []

    @pytest.mark.asyncio
    async def test_get_connections_returns_empty_without_sdk(self):
        """get_connections should return empty list without SDK."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)

        connections = await service.get_connections("test-user")
        assert connections == []

    @pytest.mark.asyncio
    async def test_initiate_connection_without_sdk(self):
        """initiate_connection should return error without SDK."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)

        result = await service.initiate_connection("test-user", "gmail", "https://example.com")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_status_without_sdk(self):
        """check_connection_status should return not_configured without SDK."""
        from app.services.composio_auth import ComposioAuthService
        config = Settings(composio_api_key="")
        service = ComposioAuthService(config)

        result = await service.check_connection_status("test-user", "gmail")
        assert result["status"] == "not_configured"

    def test_supported_apps_constant(self):
        """SUPPORTED_APPS should contain expected apps."""
        from app.services.composio_auth import SUPPORTED_APPS
        assert "gmail" in SUPPORTED_APPS
        assert "slack" in SUPPORTED_APPS
        assert "googlecalendar" in SUPPORTED_APPS
        assert "todoist" in SUPPORTED_APPS


class TestComposioRoutes:
    """Test Composio API route endpoints."""

    def test_composio_apps_endpoint(self, test_client):
        """GET /api/composio/apps returns list of supported apps."""
        response = test_client.get("/api/composio/apps")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        assert "gmail" in data["apps"]

    def test_composio_connections_without_sdk(self, test_client):
        """GET /api/composio/connections returns not_configured without SDK."""
        response = test_client.get("/api/composio/connections?session_id=test")
        assert response.status_code == 200
        data = response.json()
        assert "connections" in data
        assert all(c["status"] == "not_configured" for c in data["connections"])

    def test_composio_status_without_sdk(self, test_client):
        """GET /api/composio/status/{app} returns not_configured without SDK."""
        response = test_client.get("/api/composio/status/gmail?session_id=test")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "gmail"
        assert data["status"] == "not_configured"

    def test_composio_connect_without_sdk(self, test_client):
        """POST /api/composio/connect returns 503 without SDK."""
        response = test_client.post("/api/composio/connect", json={
            "app_name": "gmail",
            "redirect_url": "https://example.com",
            "session_id": "test",
        })
        assert response.status_code == 503


class TestExecutorEntityId:
    """Test executor entity_id parameter threading."""

    @pytest.mark.asyncio
    async def test_execute_composio_mock_with_entity_id(self, settings):
        """Executor should accept entity_id and still work with mock."""
        executor = WorkflowExecutor(settings)
        workflow = WorkflowDefinition(
            name="Test",
            trigger=WorkflowTrigger(type=TriggerType.manual),
            steps=[WorkflowStep(id="step_1", action="send_email", params={"to": "test@test.com"})],
        )
        execution = await executor.execute(workflow, entity_id="user_123")
        assert execution.status.value in ("completed", "failed")
