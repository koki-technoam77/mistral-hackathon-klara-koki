import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Optional

from app.models.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


class SavedWorkflow:
    """Lightweight wrapper for a persisted workflow + metadata."""

    def __init__(
        self,
        id: str,
        workflow: WorkflowDefinition,
        session_id: str,
        created_at: str,
        last_run_at: Optional[str] = None,
        run_count: int = 0,
    ):
        self.id = id
        self.workflow = workflow
        self.session_id = session_id
        self.created_at = created_at
        self.last_run_at = last_run_at
        self.run_count = run_count

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow": self.workflow.model_dump(mode="json"),
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "run_count": self.run_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SavedWorkflow":
        return cls(
            id=data["id"],
            workflow=WorkflowDefinition.model_validate(data["workflow"]),
            session_id=data.get("session_id", "default"),
            created_at=data.get("created_at", ""),
            last_run_at=data.get("last_run_at"),
            run_count=data.get("run_count", 0),
        )


class WorkflowStorageService:
    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = storage_dir
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)

    @staticmethod
    def _safe_id(raw: str) -> str:
        if _SAFE_ID_RE.match(raw):
            return raw
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _session_dir(self, session_id: str) -> str:
        if not self._storage_dir:
            return ""
        sid = self._safe_id(session_id)
        path = os.path.join(self._storage_dir, sid)
        os.makedirs(path, exist_ok=True)
        return path

    def _path_for(self, session_id: str, workflow_id: str) -> str:
        sdir = self._session_dir(session_id)
        if not sdir:
            return ""
        return os.path.join(sdir, f"{self._safe_id(workflow_id)}.json")

    @staticmethod
    def _make_id(workflow: WorkflowDefinition) -> str:
        """Deterministic ID from workflow name + step IDs."""
        key = f"{workflow.name}|{'|'.join(s.id for s in workflow.steps)}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def save(
        self, workflow: WorkflowDefinition, session_id: str = "default"
    ) -> SavedWorkflow:
        if not self._storage_dir:
            raise RuntimeError("Workflow storage not configured")

        wf_id = self._make_id(workflow)
        path = self._path_for(session_id, wf_id)

        # Merge with existing if re-saving
        existing: Optional[SavedWorkflow] = None
        if os.path.exists(path):
            try:
                with open(path) as f:
                    existing = SavedWorkflow.from_dict(json.load(f))
            except Exception:
                pass

        saved = SavedWorkflow(
            id=wf_id,
            workflow=workflow,
            session_id=session_id,
            created_at=existing.created_at if existing else datetime.now(tz=UTC).isoformat(),
            last_run_at=existing.last_run_at if existing else None,
            run_count=existing.run_count if existing else 0,
        )

        try:
            with open(path, "w") as f:
                json.dump(saved.to_dict(), f)
        except Exception:
            logger.warning("Failed to persist workflow %s", wf_id, exc_info=True)

        return saved

    def list(self, session_id: str = "default") -> list[dict]:
        if not self._storage_dir:
            return []
        sdir = self._session_dir(session_id)
        if not sdir or not os.path.isdir(sdir):
            return []

        results: list[dict] = []
        for fname in sorted(os.listdir(sdir)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(sdir, fname)) as f:
                    data = json.load(f)
                saved = SavedWorkflow.from_dict(data)
                results.append(saved.to_dict())
            except Exception:
                logger.warning("Failed to load workflow %s", fname, exc_info=True)
        return results

    def get(self, workflow_id: str, session_id: str = "default") -> Optional[SavedWorkflow]:
        if not self._storage_dir:
            return None
        path = self._path_for(session_id, workflow_id)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                return SavedWorkflow.from_dict(json.load(f))
        except Exception:
            logger.warning("Failed to load workflow %s", workflow_id, exc_info=True)
            return None

    def delete(self, workflow_id: str, session_id: str = "default") -> bool:
        if not self._storage_dir:
            return False
        path = self._path_for(session_id, workflow_id)
        if not path or not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            logger.warning("Failed to delete workflow %s", workflow_id, exc_info=True)
            return False

    def record_run(self, workflow_id: str, session_id: str = "default") -> None:
        """Increment run_count and update last_run_at."""
        saved = self.get(workflow_id, session_id)
        if not saved:
            return
        saved.run_count += 1
        saved.last_run_at = datetime.now(tz=UTC).isoformat()
        path = self._path_for(session_id, workflow_id)
        try:
            with open(path, "w") as f:
                json.dump(saved.to_dict(), f)
        except Exception:
            logger.warning("Failed to update run count for %s", workflow_id, exc_info=True)
