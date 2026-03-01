from __future__ import annotations

import json
import time
from typing import Any

import weave


_initialized = False


def init_weave(project: str = "kotoflow") -> None:
    global _initialized
    if not _initialized:
        weave.init(project)
        _initialized = True


@weave.op()
def trace_workflow_generation(
    user_request: str,
    services: list[str],
    trigger_type: str,
    result: dict[str, Any],
    model_used: str,
    latency_ms: float,
) -> dict[str, Any]:
    return {
        "user_request": user_request,
        "services": services,
        "trigger_type": trigger_type,
        "model_used": model_used,
        "latency_ms": latency_ms,
        "step_count": len(result.get("steps", [])),
    }


@weave.op()
def trace_workflow_execution(
    workflow_name: str,
    step_count: int,
    status: str,
    step_results: dict[str, Any],
    duration_ms: float,
) -> dict[str, Any]:
    return {
        "workflow_name": workflow_name,
        "step_count": step_count,
        "status": status,
        "duration_ms": duration_ms,
        "steps_succeeded": sum(1 for r in step_results.values() if r.get("success")),
    }


@weave.op()
def trace_feedback(
    workflow: dict[str, Any],
    feedback_type: str,
    edited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "feedback_type": feedback_type,
        "timestamp": time.time(),
        "original": workflow,
    }
    if feedback_type in ("edit", "edited") and edited:
        record["edited"] = edited
    return record


class FeedbackCollector:
    def __init__(self, output_path: str = "/tmp/kotoflow_feedback.jsonl"):
        self.output_path = output_path

    def save_chosen(self, user_request: str, workflow: dict[str, Any]) -> None:
        self._append({"messages": [{"role": "user", "content": user_request}],
                       "chosen": {"role": "assistant", "content": json.dumps(workflow)}})

    def save_rejected(self, user_request: str, workflow: dict[str, Any]) -> None:
        self._append({"messages": [{"role": "user", "content": user_request}],
                       "rejected": {"role": "assistant", "content": json.dumps(workflow)}})

    def collect(
        self, user_request: str, workflow: dict[str, Any],
        feedback_type: str, edited: dict[str, Any] | None = None,
    ) -> None:
        trace_feedback(workflow, feedback_type, edited)
        if feedback_type == "accept":
            self.save_chosen(user_request, workflow)
        elif feedback_type == "edit" and edited:
            self.save_chosen(user_request, edited)
            self.save_rejected(user_request, workflow)
        elif feedback_type == "reject":
            self.save_rejected(user_request, workflow)

    def _append(self, record: dict[str, Any]) -> None:
        with open(self.output_path, "a") as f:
            f.write(json.dumps(record) + "\n")
