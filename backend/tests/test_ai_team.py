"""Tests for multi-AI team orchestration (Claude / Codex / Gemini)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.config import Settings
from app.models.ai_team import (
    AIProvider,
    OrchestrationStrategy,
    ProviderResult,
    TaskType,
    TeamTaskRequest,
    TASK_ROUTING,
)
from app.services.ai_team import AITeamOrchestrator
from app.services.ai_providers.base import OAuthTokenManager


# ============================================================================
# MODEL TESTS
# ============================================================================

class TestAITeamModels:
    """Test AI team model definitions."""

    def test_ai_provider_enum_values(self):
        assert AIProvider.claude.value == "claude"
        assert AIProvider.codex.value == "codex"
        assert AIProvider.gemini.value == "gemini"
        assert AIProvider.mistral.value == "mistral"

    def test_task_type_enum_values(self):
        assert TaskType.reasoning.value == "reasoning"
        assert TaskType.code_generation.value == "code_generation"
        assert TaskType.multimodal.value == "multimodal"

    def test_orchestration_strategy_enum_values(self):
        assert OrchestrationStrategy.route.value == "route"
        assert OrchestrationStrategy.consensus.value == "consensus"
        assert OrchestrationStrategy.fallback.value == "fallback"
        assert OrchestrationStrategy.parallel.value == "parallel"

    def test_task_routing_covers_all_task_types(self):
        for task_type in TaskType:
            assert task_type in TASK_ROUTING

    def test_team_task_request_defaults(self):
        req = TeamTaskRequest(prompt="test")
        assert req.task_type == TaskType.general
        assert req.strategy == OrchestrationStrategy.route
        assert req.preferred_provider is None
        assert req.max_tokens == 2048

    def test_team_task_request_validation(self):
        with pytest.raises(ValueError):
            TeamTaskRequest(prompt="")  # min_length=1

    def test_provider_result_success(self):
        result = ProviderResult(
            provider=AIProvider.claude,
            content="Hello",
            latency_ms=100.0,
        )
        assert result.success is True
        assert result.error is None

    def test_provider_result_failure(self):
        result = ProviderResult(
            provider=AIProvider.codex,
            content="",
            latency_ms=50.0,
            success=False,
            error="Connection failed",
        )
        assert result.success is False


# ============================================================================
# OAUTH TOKEN MANAGER TESTS
# ============================================================================

class TestOAuthTokenManager:
    """Test OAuth token management."""

    def test_token_manager_init(self):
        mgr = OAuthTokenManager(
            token_url="https://auth.example.com/token",
            client_id="client-123",
            client_secret="secret-456",
            scopes=["read", "write"],
        )
        assert mgr.token_url == "https://auth.example.com/token"
        assert mgr.client_id == "client-123"
        assert mgr.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_token_returns_none_without_credentials(self):
        mgr = OAuthTokenManager(
            token_url="https://auth.example.com/token",
            client_id="",
            client_secret="",
        )
        token = await mgr.get_token()
        assert token is None


# ============================================================================
# AI TEAM ORCHESTRATOR TESTS
# ============================================================================

class TestAITeamOrchestrator:
    """Test the AI team orchestration logic."""

    def _make_settings(self, **overrides):
        defaults = dict(
            mistral_api_key="test-key",
            anthropic_api_key="test-anthropic",
            openai_api_key="test-openai",
            gemini_api_key="test-gemini",
            cors_origins="http://localhost:3000",
        )
        defaults.update(overrides)
        return Settings(**defaults)

    def test_available_providers_all_configured(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)
        available = team.available_providers()
        assert AIProvider.claude in available
        assert AIProvider.codex in available
        assert AIProvider.gemini in available

    def test_available_providers_partial(self):
        settings = self._make_settings(
            anthropic_api_key="test-key",
            openai_api_key="",
            gemini_api_key="",
        )
        team = AITeamOrchestrator(settings)
        available = team.available_providers()
        assert AIProvider.claude in available
        assert AIProvider.codex not in available
        assert AIProvider.gemini not in available

    def test_available_providers_none(self):
        settings = self._make_settings(
            anthropic_api_key="",
            openai_api_key="",
            gemini_api_key="",
        )
        team = AITeamOrchestrator(settings)
        assert team.available_providers() == []

    def test_provider_order_for_reasoning(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)
        request = TeamTaskRequest(prompt="analyze this", task_type=TaskType.reasoning)
        order = team._get_provider_order(request)
        # Claude should be first for reasoning
        assert order[0] == AIProvider.claude

    def test_provider_order_for_code_generation(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)
        request = TeamTaskRequest(prompt="write code", task_type=TaskType.code_generation)
        order = team._get_provider_order(request)
        # Codex should be first for code generation
        assert order[0] == AIProvider.codex

    def test_provider_order_for_multimodal(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)
        request = TeamTaskRequest(prompt="analyze image", task_type=TaskType.multimodal)
        order = team._get_provider_order(request)
        # Gemini should be first for multimodal
        assert order[0] == AIProvider.gemini

    def test_preferred_provider_overrides_routing(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)
        request = TeamTaskRequest(
            prompt="test",
            task_type=TaskType.reasoning,
            preferred_provider=AIProvider.codex,
        )
        order = team._get_provider_order(request)
        assert order[0] == AIProvider.codex

    @pytest.mark.asyncio
    async def test_execute_route_strategy(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        mock_result = ProviderResult(
            provider=AIProvider.claude,
            content="Test response",
            latency_ms=150.0,
            token_usage={"input": 10, "output": 20},
        )

        with patch.object(
            team.providers[AIProvider.claude], "generate",
            new_callable=AsyncMock, return_value=mock_result,
        ):
            request = TeamTaskRequest(
                prompt="analyze this",
                task_type=TaskType.reasoning,
                strategy=OrchestrationStrategy.route,
            )
            response = await team.execute(request)

        assert response.strategy_used == OrchestrationStrategy.route
        assert response.primary_provider == AIProvider.claude
        assert response.final_result == "Test response"

    @pytest.mark.asyncio
    async def test_execute_fallback_strategy(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        failed_result = ProviderResult(
            provider=AIProvider.claude,
            content="",
            latency_ms=50.0,
            success=False,
            error="Failed",
        )
        success_result = ProviderResult(
            provider=AIProvider.codex,
            content="Fallback response",
            latency_ms=200.0,
        )

        with patch.object(
            team.providers[AIProvider.claude], "generate",
            new_callable=AsyncMock, return_value=failed_result,
        ), patch.object(
            team.providers[AIProvider.codex], "generate",
            new_callable=AsyncMock, return_value=success_result,
        ):
            request = TeamTaskRequest(
                prompt="test",
                task_type=TaskType.general,
                strategy=OrchestrationStrategy.fallback,
            )
            response = await team.execute(request)

        assert response.strategy_used == OrchestrationStrategy.fallback
        assert response.primary_provider == AIProvider.codex
        assert response.final_result == "Fallback response"
        assert len(response.provider_results) == 2

    @pytest.mark.asyncio
    async def test_execute_parallel_strategy_returns_fastest(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        claude_result = ProviderResult(
            provider=AIProvider.claude,
            content="Claude response",
            latency_ms=300.0,
        )
        codex_result = ProviderResult(
            provider=AIProvider.codex,
            content="Codex response",
            latency_ms=100.0,  # fastest
        )
        gemini_result = ProviderResult(
            provider=AIProvider.gemini,
            content="Gemini response",
            latency_ms=200.0,
        )

        with patch.object(
            team.providers[AIProvider.claude], "generate",
            new_callable=AsyncMock, return_value=claude_result,
        ), patch.object(
            team.providers[AIProvider.codex], "generate",
            new_callable=AsyncMock, return_value=codex_result,
        ), patch.object(
            team.providers[AIProvider.gemini], "generate",
            new_callable=AsyncMock, return_value=gemini_result,
        ):
            request = TeamTaskRequest(
                prompt="test",
                strategy=OrchestrationStrategy.parallel,
            )
            response = await team.execute(request)

        assert response.strategy_used == OrchestrationStrategy.parallel
        assert response.primary_provider == AIProvider.codex
        assert response.final_result == "Codex response"
        assert len(response.provider_results) == 3

    @pytest.mark.asyncio
    async def test_execute_consensus_strategy(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        claude_result = ProviderResult(
            provider=AIProvider.claude,
            content="Claude says X",
            latency_ms=200.0,
        )
        codex_result = ProviderResult(
            provider=AIProvider.codex,
            content="Codex says Y",
            latency_ms=150.0,
        )
        gemini_result = ProviderResult(
            provider=AIProvider.gemini,
            content="Gemini says Z",
            latency_ms=180.0,
        )
        synth_result = ProviderResult(
            provider=AIProvider.claude,
            content="Synthesized: X+Y+Z",
            latency_ms=100.0,
        )

        with patch.object(
            team.providers[AIProvider.claude], "generate",
            new_callable=AsyncMock, side_effect=[claude_result, synth_result],
        ), patch.object(
            team.providers[AIProvider.codex], "generate",
            new_callable=AsyncMock, return_value=codex_result,
        ), patch.object(
            team.providers[AIProvider.gemini], "generate",
            new_callable=AsyncMock, return_value=gemini_result,
        ):
            request = TeamTaskRequest(
                prompt="test",
                strategy=OrchestrationStrategy.consensus,
            )
            response = await team.execute(request)

        assert response.strategy_used == OrchestrationStrategy.consensus
        assert "Synthesized" in response.final_result

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_empty(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        failed = ProviderResult(
            provider=AIProvider.claude,
            content="",
            latency_ms=50.0,
            success=False,
            error="Failed",
        )

        for provider in team.providers.values():
            provider.generate = AsyncMock(return_value=ProviderResult(
                provider=provider.provider,
                content="",
                latency_ms=50.0,
                success=False,
                error="Failed",
            ))

        request = TeamTaskRequest(
            prompt="test",
            strategy=OrchestrationStrategy.fallback,
        )
        response = await team.execute(request)

        assert "No AI providers available" in response.final_result

    @pytest.mark.asyncio
    async def test_status_returns_all_providers(self):
        settings = self._make_settings()
        team = AITeamOrchestrator(settings)

        for provider in team.providers.values():
            provider.health_check = AsyncMock(return_value=True)

        status = await team.get_status()

        assert len(status.providers) == 3
        provider_names = {p.provider for p in status.providers}
        assert AIProvider.claude in provider_names
        assert AIProvider.codex in provider_names
        assert AIProvider.gemini in provider_names
