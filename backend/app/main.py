import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings
from app.utils.wandb_tracking import init_weave

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "microphone=(self)"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if settings.wandb_api_key:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(init_weave, settings.wandb_project),
                timeout=10,
            )
        except Exception:
            logger.warning("Weave/W&B init timed out or failed — tracing disabled")
    yield
    # Cleanup: close persistent httpx clients and scheduler
    from app.api.routes import _anam_service, _scheduler
    if _scheduler is not None:
        _scheduler.stop()
    if _anam_service is not None:
        await _anam_service.aclose()


app = FastAPI(title="KotoFlow API", version="0.1.0", lifespan=lifespan)

settings = Settings()

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)

from app.api.routes import router  # noqa: E402
from app.api.websocket import router as ws_router  # noqa: E402

app.include_router(router, prefix="/api")
app.include_router(ws_router, prefix="/ws")
