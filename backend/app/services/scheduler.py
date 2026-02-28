"""Workflow scheduler — cron and interval execution via APScheduler.

Runs in-process with an in-memory job store. Suitable for single-instance
deployment (Railway, Render, etc.). For HA, swap to a persistent store.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.models.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)

MAX_SCHEDULED_JOBS = 50


class ScheduledJob:
    """In-memory representation of a scheduled workflow."""

    __slots__ = (
        "job_id", "workflow", "entity_id", "cron_expr", "interval_seconds",
        "created_at", "last_run_at", "last_status", "run_count",
    )

    def __init__(
        self,
        workflow: WorkflowDefinition,
        entity_id: str,
        cron_expr: Optional[str] = None,
        interval_seconds: Optional[int] = None,
    ):
        self.job_id = str(uuid4())
        self.workflow = workflow
        self.entity_id = entity_id
        self.cron_expr = cron_expr
        self.interval_seconds = interval_seconds
        self.created_at = datetime.now(tz=UTC)
        self.last_run_at: Optional[datetime] = None
        self.last_status: Optional[str] = None
        self.run_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workflow_name": self.workflow.name,
            "entity_id": self.entity_id,
            "cron_expr": self.cron_expr,
            "interval_seconds": self.interval_seconds,
            "created_at": self.created_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_status": self.last_status,
            "run_count": self.run_count,
        }


class WorkflowScheduler:
    def __init__(self, executor: Any):
        self._executor = executor
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, ScheduledJob] = {}
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("Workflow scheduler started")

    def stop(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("Workflow scheduler stopped")

    def schedule_cron(
        self,
        workflow: WorkflowDefinition,
        cron_expr: str,
        entity_id: str = "default",
    ) -> ScheduledJob:
        """Schedule a workflow to run on a cron expression (5-field)."""
        if len(self._jobs) >= MAX_SCHEDULED_JOBS:
            raise ValueError("Maximum scheduled jobs reached")

        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields")

        job_info = ScheduledJob(
            workflow=workflow,
            entity_id=entity_id,
            cron_expr=cron_expr,
        )

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self._scheduler.add_job(
            self._run_workflow,
            trigger=trigger,
            id=job_info.job_id,
            args=[job_info],
            replace_existing=True,
        )

        self._jobs[job_info.job_id] = job_info
        logger.info("Scheduled cron job %s: %s (%s)", job_info.job_id, workflow.name, cron_expr)
        return job_info

    def schedule_interval(
        self,
        workflow: WorkflowDefinition,
        seconds: int,
        entity_id: str = "default",
    ) -> ScheduledJob:
        """Schedule a workflow to run at a fixed interval."""
        if len(self._jobs) >= MAX_SCHEDULED_JOBS:
            raise ValueError("Maximum scheduled jobs reached")

        if seconds < 60:
            raise ValueError("Minimum interval is 60 seconds")
        if seconds > 86400:
            raise ValueError("Maximum interval is 86400 seconds (24h)")

        job_info = ScheduledJob(
            workflow=workflow,
            entity_id=entity_id,
            interval_seconds=seconds,
        )

        self._scheduler.add_job(
            self._run_workflow,
            trigger=IntervalTrigger(seconds=seconds),
            id=job_info.job_id,
            args=[job_info],
            replace_existing=True,
        )

        self._jobs[job_info.job_id] = job_info
        logger.info("Scheduled interval job %s: %s (every %ds)", job_info.job_id, workflow.name, seconds)
        return job_info

    def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        if job_id not in self._jobs:
            return False
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        del self._jobs[job_id]
        logger.info("Cancelled scheduled job %s", job_id)
        return True

    def list_jobs(self, entity_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List all scheduled jobs, optionally filtered by entity_id."""
        jobs = self._jobs.values()
        if entity_id:
            jobs = [j for j in jobs if j.entity_id == entity_id]
        return [j.to_dict() for j in jobs]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    async def _run_workflow(self, job_info: ScheduledJob) -> None:
        """Execute a scheduled workflow."""
        logger.info("Running scheduled workflow: %s (job %s)", job_info.workflow.name, job_info.job_id)
        try:
            execution = await self._executor.execute(
                job_info.workflow,
                entity_id=job_info.entity_id,
            )
            job_info.last_status = execution.status.value
            job_info.last_run_at = datetime.now(tz=UTC)
            job_info.run_count += 1
            logger.info(
                "Scheduled workflow %s completed: %s (run #%d)",
                job_info.workflow.name, execution.status.value, job_info.run_count,
            )
        except Exception:
            job_info.last_status = "failed"
            job_info.last_run_at = datetime.now(tz=UTC)
            job_info.run_count += 1
            logger.error("Scheduled workflow %s failed", job_info.workflow.name, exc_info=True)
