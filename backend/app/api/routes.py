import asyncio
import json
import logging
import secrets
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import Settings
from app.models.character import CharacterState
from app.models.ai_team import (
    AIProvider,
    OrchestrationStrategy,
    TaskType,
    TeamTaskRequest,
    TeamTaskResponse,
    TeamStatus,
)
from app.models.workflow import WorkflowDefinition, WorkflowExecution
from app.services.ai_team import AITeamOrchestrator
from app.services.character import CharacterService
from app.services.executor import WorkflowExecutor
from app.services.orchestrator import OrchestratorAgent, OrchestratorResponse
from app.services.anam import AnamService
from app.services.composio_auth import ComposioAuthService
from app.services.voice import VoiceService
from app.services.workflow_gen import WorkflowGenerator

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/wav", "audio/mpeg", "audio/ogg", "audio/mp4"}
MAX_HISTORY_PER_SESSION = 20

_settings: Optional[Settings] = None
_workflow_generator: Optional[WorkflowGenerator] = None
_workflow_executor: Optional[WorkflowExecutor] = None
_voice_service: Optional[VoiceService] = None
_character_service: Optional[CharacterService] = None
_ai_team: Optional[AITeamOrchestrator] = None
_anam_service: Optional[AnamService] = None
_composio_auth: Optional[ComposioAuthService] = None
_sessions: dict[str, tuple[OrchestratorAgent, float]] = {}
_SESSION_TTL = 3600  # 1 hour
_MAX_SESSIONS = 1000


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    settings = _get_settings()
    if not settings.kotoflow_api_key:
        return  # No API key configured = open access (dev mode)
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authentication")
    if not secrets.compare_digest(credentials.credentials, settings.kotoflow_api_key):
        raise HTTPException(status_code=401, detail="Invalid authentication")


def _get_orchestrator(session_id: str) -> OrchestratorAgent:
    settings = _get_settings()
    now = time.time()

    # Evict expired sessions
    expired = [sid for sid, (_, ts) in _sessions.items() if now - ts > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]

    if session_id not in _sessions:
        if len(_sessions) >= _MAX_SESSIONS:
            raise HTTPException(status_code=429, detail="Too many active sessions")
        _sessions[session_id] = (OrchestratorAgent(settings), now)
    else:
        agent, _ = _sessions[session_id]
        _sessions[session_id] = (agent, now)  # Refresh timestamp

    return _sessions[session_id][0]


def _get_services():
    global _workflow_generator, _workflow_executor, _voice_service, _character_service, _ai_team, _anam_service, _composio_auth

    settings = _get_settings()

    if _workflow_generator is None:
        _workflow_generator = WorkflowGenerator(settings)
    if _workflow_executor is None:
        _workflow_executor = WorkflowExecutor(settings)
    if _voice_service is None:
        _voice_service = VoiceService(settings)
    if _character_service is None:
        _character_service = CharacterService()
    if _ai_team is None:
        _ai_team = AITeamOrchestrator(settings)
    if _anam_service is None:
        _anam_service = AnamService(settings)
    if _composio_auth is None:
        _composio_auth = ComposioAuthService(settings)

    return {
        "workflow_generator": _workflow_generator,
        "workflow_executor": _workflow_executor,
        "voice_service": _voice_service,
        "character_service": _character_service,
        "ai_team": _ai_team,
        "anam_service": _anam_service,
        "composio_auth": _composio_auth,
    }


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(default_factory=lambda: str(uuid4()))


class ChatResponse(BaseModel):
    message: str
    ready: bool
    workflow: Optional[WorkflowDefinition] = None
    character_state: CharacterState
    session_id: str


ALLOWED_SERVICES = frozenset([
    "Gmail", "Slack", "Discord", "Twitter", "Google Sheets", "Google Calendar",
    "Notion", "Trello", "GitHub", "Jira", "Linear", "Salesforce", "HubSpot",
    "Zapier", "Airtable", "Dropbox", "OneDrive", "Teams", "Telegram", "WhatsApp",
])


class WorkflowGenerateRequest(BaseModel):
    request_summary: str = Field(..., min_length=1, max_length=500)
    services: list[str] = Field(..., max_length=10)
    trigger_type: str
    trigger_config: dict

    @staticmethod
    def _sanitize_text(text: str) -> str:
        import re
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


class WorkflowExecuteRequest(BaseModel):
    workflow: WorkflowDefinition
    session_id: str = "default"


class WorkflowExecuteResponse(BaseModel):
    execution: WorkflowExecution
    xp_result: dict
    character_state: CharacterState


class WorkflowFeedbackRequest(BaseModel):
    user_request: str = Field(..., max_length=500)
    workflow: WorkflowDefinition
    feedback_type: str = Field(..., pattern=r"^(accept|reject|edit)$")
    edited: Optional[dict] = None


class VoiceTranscribeResponse(BaseModel):
    text: str


class VoiceSynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    session_id: str = "default"


class VoiceSynthesizePcmRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    session_id: str = "default"


class AnamSessionResponse(BaseModel):
    session_token: str
    elevenlabs_agent_id: str


class HealthResponse(BaseModel):
    status: str


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(_verify_api_key)])
async def chat(request: ChatRequest):
    services = _get_services()
    orchestrator = _get_orchestrator(request.session_id)

    try:
        orchestrator_response: OrchestratorResponse = await orchestrator.chat(request.message)

        workflow = None
        if orchestrator_response.ready and orchestrator_response.workflow_request:
            try:
                workflow = await services["workflow_generator"].generate(
                    request_summary=orchestrator_response.workflow_request.get("request_summary", ""),
                    services=orchestrator_response.workflow_request.get("services", []),
                    trigger_type=orchestrator_response.workflow_request.get("trigger_type", "manual"),
                    trigger_config=orchestrator_response.workflow_request.get("trigger_config", {}),
                )
            except Exception as e:
                logger.error("Workflow generation failed: %s", e)
                workflow = None

        character_state = services["character_service"].get_state(request.session_id)

        return ChatResponse(
            message=orchestrator_response.message,
            ready=orchestrator_response.ready,
            workflow=workflow,
            character_state=character_state,
            session_id=request.session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


class ChatResetRequest(BaseModel):
    session_id: str = ""


@router.post("/chat/reset", dependencies=[Depends(_verify_api_key)])
async def chat_reset(request: ChatResetRequest = ChatResetRequest()):
    if request.session_id and request.session_id in _sessions:
        agent, _ = _sessions[request.session_id]
        agent.reset()
        del _sessions[request.session_id]
    return {"status": "reset"}


@router.post("/workflow/generate", response_model=WorkflowDefinition, dependencies=[Depends(_verify_api_key)])
async def workflow_generate(request: WorkflowGenerateRequest):
    services = _get_services()
    if not services["workflow_generator"]:
        raise HTTPException(status_code=500, detail="Service unavailable")

    try:
        sanitized_summary = WorkflowGenerateRequest._sanitize_text(request.request_summary)
        workflow = await services["workflow_generator"].generate(
            request_summary=sanitized_summary,
            services=request.services,
            trigger_type=request.trigger_type,
            trigger_config=request.trigger_config,
        )
        return workflow
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Workflow generation error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Workflow generation failed")


@router.post("/workflow/execute", response_model=WorkflowExecuteResponse, dependencies=[Depends(_verify_api_key)])
async def workflow_execute(request: WorkflowExecuteRequest):
    services = _get_services()
    if not services["workflow_executor"]:
        raise HTTPException(status_code=500, detail="Service unavailable")

    try:
        execution = await services["workflow_executor"].execute(request.workflow, entity_id=request.session_id)

        xp_result = services["character_service"].award_xp(
            request.workflow, session_id=request.session_id
        )
        character_state = services["character_service"].get_state(request.session_id)

        return WorkflowExecuteResponse(
            execution=execution,
            xp_result=xp_result,
            character_state=character_state,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Workflow execution error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Workflow execution failed")


@router.post("/workflow/feedback", dependencies=[Depends(_verify_api_key)])
async def workflow_feedback(request: WorkflowFeedbackRequest):
    logger.info("Feedback received: %s", request.feedback_type)
    try:
        from app.utils.wandb_tracking import FeedbackCollector
        collector = FeedbackCollector()
        collector.collect(
            user_request=request.user_request,
            workflow=request.workflow.model_dump(),
            feedback_type=request.feedback_type,
            edited=request.edited,
        )
    except Exception:
        logger.error("Failed to collect feedback", exc_info=True)
    return {"status": "feedback_collected"}


@router.get("/character", response_model=CharacterState, dependencies=[Depends(_verify_api_key)])
async def get_character(session_id: str = "default"):
    services = _get_services()
    return services["character_service"].get_state(session_id)


@router.post("/voice/transcribe", response_model=VoiceTranscribeResponse, dependencies=[Depends(_verify_api_key)])
async def voice_transcribe(file: UploadFile = File(...)):
    services = _get_services()
    if not services["voice_service"]:
        raise HTTPException(status_code=500, detail="Service unavailable")

    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio format")

    try:
        audio_data = await file.read(MAX_AUDIO_BYTES + 1)
        if len(audio_data) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio file too large (max 10MB)")

        text = await services["voice_service"].transcribe(audio_data)

        if not text:
            raise HTTPException(status_code=422, detail="Transcription returned empty result")

        return VoiceTranscribeResponse(text=text)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Transcription error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Transcription failed")


@router.post("/anam/session", response_model=AnamSessionResponse, dependencies=[Depends(_verify_api_key)])
async def anam_session():
    services = _get_services()
    anam: AnamService = services["anam_service"]

    settings = _get_settings()

    if not anam.api_key:
        raise HTTPException(status_code=503, detail="Avatar service not configured")
    if not anam.avatar_id:
        raise HTTPException(status_code=503, detail="Avatar ID not configured")
    if not settings.elevenlabs_agent_id:
        raise HTTPException(status_code=503, detail="ElevenLabs Agent ID not configured")

    try:
        result = await anam.create_session()
        token = result.get("sessionToken", "")
        if not token:
            raise HTTPException(status_code=502, detail="Empty session token received")
        return AnamSessionResponse(
            session_token=token,
            elevenlabs_agent_id=settings.elevenlabs_agent_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Anam session error: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to create avatar session")


@router.post("/voice/synthesize", dependencies=[Depends(_verify_api_key)])
async def voice_synthesize(request: VoiceSynthesizeRequest):
    services = _get_services()
    if not services["voice_service"]:
        raise HTTPException(status_code=500, detail="Service unavailable")

    try:
        voice_config = services["character_service"].get_state(request.session_id).voice_config
        audio_bytes = await services["voice_service"].synthesize(request.text, voice_config)

        if not audio_bytes:
            raise HTTPException(status_code=422, detail="Synthesis returned empty audio")

        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "attachment; filename=response.mp3"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Synthesis error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Voice synthesis failed")


@router.post("/voice/synthesize-pcm", dependencies=[Depends(_verify_api_key)])
async def voice_synthesize_pcm(request: VoiceSynthesizePcmRequest):
    services = _get_services()
    if not services["voice_service"]:
        raise HTTPException(status_code=500, detail="Service unavailable")

    try:
        voice_config = services["character_service"].get_state(request.session_id).voice_config
        audio_bytes = await services["voice_service"].synthesize_pcm_chunked(request.text, voice_config)

        if not audio_bytes:
            raise HTTPException(status_code=422, detail="PCM synthesis returned empty audio")

        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/L16;rate=16000;channels=1",
            headers={"Content-Disposition": "attachment; filename=response.pcm"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("PCM synthesis error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Voice synthesis failed")


# ──────────────────────────────────────────────────────────────────
# SSE Streaming Execution Endpoint
# ──────────────────────────────────────────────────────────────────

@router.post("/workflow/execute-stream", dependencies=[Depends(_verify_api_key)])
async def workflow_execute_stream(request: WorkflowExecuteRequest):
    services = _get_services()
    executor: WorkflowExecutor = services["workflow_executor"]

    async def event_generator():
        step_results = {}
        executed_steps: set[str] = set()

        for step in request.workflow.steps:
            if step.depends_on and not all(d in executed_steps for d in step.depends_on):
                continue

            yield f"data: {json.dumps({'type': 'step_start', 'step_id': step.id})}\n\n"

            try:
                context = {"previous_results": step_results}
                result = await executor._execute_step(step, context, entity_id=request.session_id)
                step_results[step.id] = result
                if step.output:
                    step_results[f"{step.id}.{step.output}"] = result
                executed_steps.add(step.id)

                yield f"data: {json.dumps({'type': 'step_complete', 'step_id': step.id, 'status': 'success'})}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type': 'step_error', 'step_id': step.id})}\n\n"

        xp_result = services["character_service"].award_xp(
            request.workflow, session_id=request.session_id
        )
        character_state = services["character_service"].get_state(request.session_id)

        done_payload = {
            "type": "done",
            "result": WorkflowExecuteResponse(
                execution=WorkflowExecution(
                    workflow=request.workflow,
                    status="completed",
                    step_results=step_results,
                ),
                xp_result=xp_result,
                character_state=character_state,
            ).model_dump(mode="json"),
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────────────────────────
# AI Team Orchestration Endpoints
# ──────────────────────────────────────────────────────────────────

class TeamChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    task_type: str = "general"
    strategy: str = "route"
    preferred_provider: Optional[str] = None
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    session_id: str = Field(default_factory=lambda: str(uuid4()))


@router.post("/team/execute", response_model=TeamTaskResponse, dependencies=[Depends(_verify_api_key)])
async def team_execute(request: TeamChatRequest):
    """Execute a task using the multi-AI orchestration team."""
    services = _get_services()
    ai_team: AITeamOrchestrator = services["ai_team"]

    if not ai_team.available_providers():
        raise HTTPException(status_code=503, detail="No AI providers configured")

    try:
        task_request = TeamTaskRequest(
            prompt=request.prompt,
            task_type=TaskType(request.task_type),
            strategy=OrchestrationStrategy(request.strategy),
            preferred_provider=AIProvider(request.preferred_provider) if request.preferred_provider else None,
            max_tokens=request.max_tokens,
            session_id=request.session_id,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task_type, strategy, or provider")

    try:
        response = await ai_team.execute(task_request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI team execution error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="AI team execution failed")


@router.get("/team/status", response_model=TeamStatus, dependencies=[Depends(_verify_api_key)])
async def team_status():
    """Get the health and status of all AI providers in the team."""
    services = _get_services()
    ai_team: AITeamOrchestrator = services["ai_team"]

    try:
        return await ai_team.get_status()
    except Exception as e:
        logger.error("AI team status error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Status check failed")


@router.get("/team/providers", dependencies=[Depends(_verify_api_key)])
async def team_providers():
    """List available AI providers."""
    services = _get_services()
    ai_team: AITeamOrchestrator = services["ai_team"]
    available = ai_team.available_providers()
    return {
        "providers": [p.value for p in available],
        "count": len(available),
        "strategies": [s.value for s in OrchestrationStrategy],
        "task_types": [t.value for t in TaskType],
    }


# ──────────────────────────────────────────────────────────────────
# Composio OAuth Connection Endpoints
# ──────────────────────────────────────────────────────────────────


class ComposioConnectRequest(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=50)
    redirect_url: str = Field(..., min_length=1, max_length=500)
    session_id: str = "default"


class ComposioConnectionStatus(BaseModel):
    app: str
    status: str
    connected_account_id: Optional[str] = None


@router.get("/composio/apps", dependencies=[Depends(_verify_api_key)])
async def composio_apps():
    """List supported Composio apps."""
    from app.services.composio_auth import SUPPORTED_APPS
    return {"apps": SUPPORTED_APPS}


@router.get("/composio/connections", dependencies=[Depends(_verify_api_key)])
async def composio_connections(session_id: str = "default"):
    """Get connection status for all supported apps for this user."""
    services = _get_services()
    composio_auth = services.get("composio_auth")
    if not composio_auth or not composio_auth.available:
        from app.services.composio_auth import SUPPORTED_APPS
        return {"connections": [{"app": app, "status": "not_configured", "connected_account_id": None} for app in SUPPORTED_APPS]}

    connections = await composio_auth.get_connections(entity_id=session_id)
    return {"connections": connections}


@router.post("/composio/connect", dependencies=[Depends(_verify_api_key)])
async def composio_connect(request: ComposioConnectRequest):
    """Initiate OAuth connection for a Composio app."""
    services = _get_services()
    composio_auth = services.get("composio_auth")
    if not composio_auth or not composio_auth.available:
        raise HTTPException(status_code=503, detail="Composio not configured")

    result = await composio_auth.initiate_connection(
        entity_id=request.session_id,
        app_name=request.app_name,
        redirect_url=request.redirect_url,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "Connection failed"))
    return result


@router.get("/composio/status/{app_name}", dependencies=[Depends(_verify_api_key)])
async def composio_connection_status(app_name: str, session_id: str = "default"):
    """Check connection status for a specific app."""
    services = _get_services()
    composio_auth = services.get("composio_auth")
    if not composio_auth or not composio_auth.available:
        return ComposioConnectionStatus(app=app_name, status="not_configured")

    result = await composio_auth.check_connection_status(entity_id=session_id, app_name=app_name)
    return ComposioConnectionStatus(**result)


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")
