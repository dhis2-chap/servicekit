"""Job scheduler for async task management with in-memory asyncio implementation."""

import asyncio
import inspect
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import ulid
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .schemas import JobRecord, JobStatus

ULID = ulid.ULID

# Type aliases for scheduler job targets
type JobTarget = Callable[..., Any] | Callable[..., Awaitable[Any]] | Awaitable[Any]
type JobExecutor = Callable[[], Awaitable[Any]]


class Scheduler(BaseModel, ABC):
    """Abstract job scheduler interface for async task management."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def add_job(
        self,
        target: JobTarget,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> ULID:
        """Add a job to the scheduler and return its ID."""
        ...

    @abstractmethod
    async def get_status(self, job_id: ULID) -> JobStatus:
        """Get the status of a job."""
        ...

    @abstractmethod
    async def get_record(self, job_id: ULID) -> JobRecord:
        """Get the full record of a job."""
        ...

    @abstractmethod
    async def get_all_records(self) -> list[JobRecord]:
        """Get all job records."""
        ...

    @abstractmethod
    async def cancel(self, job_id: ULID) -> bool:
        """Cancel a running job."""
        ...

    @abstractmethod
    async def delete(self, job_id: ULID) -> None:
        """Delete a job record."""
        ...

    @abstractmethod
    async def wait(self, job_id: ULID, timeout: float | None = None) -> None:
        """Wait for a job to complete."""
        ...

    @abstractmethod
    async def get_result(self, job_id: ULID) -> Any:
        """Get the result of a completed job."""
        ...

    @abstractmethod
    async def shutdown(self, *, timeout: float | None = None) -> None:
        """Stop accepting new jobs, drain running jobs up to timeout, then cancel the rest."""
        ...


class InMemoryScheduler(Scheduler):
    """In-memory asyncio scheduler. Sync callables run in thread pool, concurrency controlled via semaphore."""

    name: str = Field(default="servicekit")
    max_concurrency: int | None = Field(default=None)

    _records: dict[ULID, JobRecord] = PrivateAttr(default_factory=dict)
    _results: dict[ULID, Any] = PrivateAttr(default_factory=dict)
    _tasks: dict[ULID, asyncio.Task[Any]] = PrivateAttr(default_factory=dict)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _sema: asyncio.Semaphore | None = PrivateAttr(default=None)
    _closed: bool = PrivateAttr(default=False)

    def __init__(self, **data: Any):
        """Initialize scheduler with optional concurrency limit."""
        super().__init__(**data)
        self._closed = False
        if self.max_concurrency and self.max_concurrency > 0:
            self._sema = asyncio.Semaphore(self.max_concurrency)

    async def set_max_concurrency(self, n: int | None) -> None:
        """Set maximum number of concurrent jobs."""
        async with self._lock:
            self.max_concurrency = n
            if n and n > 0:
                self._sema = asyncio.Semaphore(n)
            else:
                self._sema = None

    async def add_job(
        self,
        target: JobTarget,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> ULID:
        """Add a job to the scheduler and return its ID."""
        if self._closed:
            raise RuntimeError("Scheduler is shut down")

        now = datetime.now(timezone.utc)
        jid = ULID()

        record = JobRecord(
            id=jid,
            status=JobStatus.pending,
            submitted_at=now,
        )

        async with self._lock:
            if jid in self._tasks:
                raise RuntimeError(f"Job {jid!r} already scheduled")
            self._records[jid] = record

        async def _execute_target() -> Any:
            if inspect.isawaitable(target):
                if args or kwargs:
                    # Close the coroutine to avoid "coroutine was never awaited" warning
                    if inspect.iscoroutine(target):
                        target.close()
                    raise TypeError("Args/kwargs not supported when target is an awaitable object.")
                return await target
            if inspect.iscoroutinefunction(target):
                return await target(*args, **kwargs)
            return await asyncio.to_thread(target, *args, **kwargs)

        async def _runner() -> Any:
            if self._sema:
                async with self._sema:
                    return await self._run_with_state(jid, _execute_target)
            else:
                return await self._run_with_state(jid, _execute_target)

        task = asyncio.create_task(_runner(), name=f"{self.name}-job-{jid}")

        def _drain(t: asyncio.Task[Any]) -> None:
            try:
                t.result()
            except Exception:
                pass

        task.add_done_callback(_drain)

        async with self._lock:
            self._tasks[jid] = task

        return jid

    async def _run_with_state(
        self,
        jid: ULID,
        exec_fn: JobExecutor,
    ) -> Any:
        """Execute job function and manage its state transitions."""
        async with self._lock:
            rec = self._records[jid]
            rec.status = JobStatus.running
            rec.started_at = datetime.now(timezone.utc)

        try:
            result = await exec_fn()

            async with self._lock:
                rec = self._records[jid]
                rec.status = JobStatus.completed
                rec.finished_at = datetime.now(timezone.utc)
                self._results[jid] = result

            return result

        except asyncio.CancelledError:
            async with self._lock:
                rec = self._records[jid]
                rec.status = JobStatus.canceled
                rec.finished_at = datetime.now(timezone.utc)

            raise

        except Exception as e:
            tb = traceback.format_exc()
            # Extract clean error message (exception type and message only)
            error_lines = tb.strip().split("\n")
            clean_error = error_lines[-1] if error_lines else str(e)

            async with self._lock:
                rec = self._records[jid]
                rec.status = JobStatus.failed
                rec.finished_at = datetime.now(timezone.utc)
                rec.error = clean_error
                rec.error_traceback = tb

            raise

    async def get_all_records(self) -> list[JobRecord]:
        """Get all job records sorted by submission time."""
        async with self._lock:
            records = [r.model_copy(deep=True) for r in self._records.values()]

        records.sort(
            key=lambda r: getattr(r, "submitted_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

        return records

    async def get_record(self, job_id: ULID) -> JobRecord:
        """Get the full record of a job."""
        async with self._lock:
            rec = self._records.get(job_id)

            if rec is None:
                raise KeyError("Job not found")

            return rec.model_copy(deep=True)

    async def get_status(self, job_id: ULID) -> JobStatus:
        """Get the status of a job."""
        async with self._lock:
            rec = self._records.get(job_id)

            if rec is None:
                raise KeyError("Job not found")

            return rec.status

    async def get_result(self, job_id: ULID) -> Any:
        """Get the result of a completed job."""
        async with self._lock:
            rec = self._records.get(job_id)

            if rec is None:
                raise KeyError("Job not found")

            if rec.status == JobStatus.completed:
                return self._results.get(job_id)

            if rec.status == JobStatus.failed:
                msg = getattr(rec, "error", "Job failed")
                raise RuntimeError(msg)

            raise RuntimeError(f"Job not finished (status={rec.status})")

    async def wait(self, job_id: ULID, timeout: float | None = None) -> None:
        """Wait for a job to complete."""
        async with self._lock:
            task = self._tasks.get(job_id)

            if task is None:
                raise KeyError("Job not found")

        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def cancel(self, job_id: ULID) -> bool:
        """Cancel a running job."""
        async with self._lock:
            task = self._tasks.get(job_id)
            exists = job_id in self._records

        if not exists:
            raise KeyError("Job not found")

        if not task or task.done():
            return False

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        return True

    async def delete(self, job_id: ULID) -> None:
        """Delete a job record."""
        async with self._lock:
            rec = self._records.get(job_id)
            task = self._tasks.get(job_id)

        if rec is None:
            raise KeyError("Job not found")

        if task and not task.done():
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            self._records.pop(job_id, None)
            self._tasks.pop(job_id, None)
            self._results.pop(job_id, None)

    async def shutdown(self, *, timeout: float | None = None) -> None:
        """Stop accepting new jobs, drain running jobs up to timeout, then cancel the rest."""
        self._closed = True

        async with self._lock:
            pending = [task for task in self._tasks.values() if not task.done()]

        if not pending:
            return

        if timeout is None or timeout > 0:
            _, still_running = await asyncio.wait(pending, timeout=timeout)
        else:
            still_running = set(pending)

        for task in still_running:
            task.cancel()

        if still_running:
            await asyncio.gather(*still_running, return_exceptions=True)
