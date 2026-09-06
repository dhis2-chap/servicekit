"""Job scheduler for async task management with in-memory asyncio implementation."""

import asyncio
import functools
import inspect
import traceback
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import ulid
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .schemas import JobRecord, JobStatus

ULID = ulid.ULID

# Type aliases for scheduler job targets
type JobTarget = Callable[..., Any] | Callable[..., Awaitable[Any]] | Awaitable[Any]
type JobExecutor = Callable[[], Awaitable[Any]]


class _CapacityLimiter:
    """Resizable concurrency limiter whose limit changes also apply to already-waiting acquirers."""

    def __init__(self, limit: int | None = None) -> None:
        """Initialize the limiter with an optional concurrency limit."""
        self._limit: int | None = limit
        self._active: int = 0
        self._waiters: deque[asyncio.Future[None]] = deque()

    @property
    def active(self) -> int:
        """Number of capacity slots currently held."""
        return self._active

    @property
    def limit(self) -> int | None:
        """Current concurrency limit, or None when unlimited."""
        return self._limit

    async def acquire(self) -> None:
        """Wait until a capacity slot is available, then take it."""
        while not self._has_capacity():
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)

            try:
                await waiter
            except asyncio.CancelledError:
                self._remove_waiter(waiter)
                self._notify_waiters()
                raise

        self._active += 1

    def release(self) -> None:
        """Return a capacity slot and let waiters re-check for available capacity."""
        self._active -= 1
        self._notify_waiters()

    def set_limit(self, limit: int | None) -> None:
        """Change the concurrency limit in place so existing waiters re-check it."""
        self._limit = limit
        self._notify_waiters()

    def _has_capacity(self) -> bool:
        """Report whether another capacity slot may be taken right now."""
        return self._limit is None or self._active < self._limit

    def _notify_waiters(self) -> None:
        """Wake every waiter so each re-checks the current limit and active count."""
        while self._waiters:
            waiter = self._waiters.popleft()

            if not waiter.done():
                waiter.set_result(None)

    def _remove_waiter(self, waiter: asyncio.Future[None]) -> None:
        """Drop a waiter that is no longer waiting for capacity."""
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass


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
    """In-memory asyncio scheduler; sync callables run in a thread pool with a resizable concurrency limit.

    Subclasses should customize behavior through the protected hooks `_make_record` and `_on_job_result`
    rather than by overriding `add_job`, so that cancellation and capacity handling stay in one place.
    """

    name: str = Field(default="servicekit")
    max_concurrency: int | None = Field(default=None, ge=1)

    _records: dict[ULID, JobRecord] = PrivateAttr(default_factory=dict)
    _results: dict[ULID, Any] = PrivateAttr(default_factory=dict)
    _tasks: dict[ULID, asyncio.Task[Any]] = PrivateAttr(default_factory=dict)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _closed: bool = PrivateAttr(default=False)
    _limiter: _CapacityLimiter = PrivateAttr(default_factory=_CapacityLimiter)
    _deferred_releases: set[ULID] = PrivateAttr(default_factory=set)
    _background_tasks: set[asyncio.Task[None]] = PrivateAttr(default_factory=set)

    def __init__(self, **data: Any):
        """Initialize scheduler with optional concurrency limit."""
        super().__init__(**data)
        self._closed = False
        self._limiter = _CapacityLimiter(self.max_concurrency)

    async def set_max_concurrency(self, max_concurrency: int | None) -> None:
        """Set maximum number of concurrent jobs, applying the new limit to already-queued jobs."""
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be None (unlimited) or at least 1")

        async with self._lock:
            self.max_concurrency = max_concurrency
            self._limiter.set_limit(max_concurrency)

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
        job_id = ULID()
        record = self._make_record(job_id, now)

        async with self._lock:
            if job_id in self._tasks:
                raise RuntimeError(f"Job {job_id!r} already scheduled")
            self._records[job_id] = record

        async def execute_target() -> Any:
            return await self._execute_target(job_id, target, *args, **kwargs)

        task = asyncio.create_task(self._runner(job_id, target, execute_target), name=f"{self.name}-job-{job_id}")
        task.add_done_callback(self._drain)

        async with self._lock:
            self._tasks[job_id] = task

        return job_id

    async def get_all_records(self) -> list[JobRecord]:
        """Get all job records sorted by submission time."""
        async with self._lock:
            records = [record.model_copy(deep=True) for record in self._records.values()]

        records.sort(
            key=lambda record: getattr(record, "submitted_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

        return records

    async def get_record(self, job_id: ULID) -> JobRecord:
        """Get the full record of a job."""
        async with self._lock:
            record = self._records.get(job_id)

            if record is None:
                raise KeyError("Job not found")

            return record.model_copy(deep=True)

    async def get_status(self, job_id: ULID) -> JobStatus:
        """Get the status of a job."""
        async with self._lock:
            record = self._records.get(job_id)

            if record is None:
                raise KeyError("Job not found")

            return record.status

    async def get_result(self, job_id: ULID) -> Any:
        """Get the result of a completed job."""
        async with self._lock:
            record = self._records.get(job_id)

            if record is None:
                raise KeyError("Job not found")

            if record.status == JobStatus.completed:
                return self._results.get(job_id)

            if record.status == JobStatus.failed:
                message = getattr(record, "error", "Job failed")
                raise RuntimeError(message)

            raise RuntimeError(f"Job not finished (status={record.status})")

    async def wait(self, job_id: ULID, timeout: float | None = None) -> None:
        """Wait for a job to complete."""
        async with self._lock:
            task = self._tasks.get(job_id)

            if task is None:
                raise KeyError("Job not found")

        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def cancel(self, job_id: ULID) -> bool:
        """Cancel a job, whether it is queued or running, returning False when it already finished.

        Synchronous targets cannot be interrupted: the record moves to `canceling` while the worker
        thread keeps running, and becomes `canceled` once the thread actually finishes.
        """
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
        """Delete a job record, canceling it first; a canceled sync job's thread may keep running."""
        async with self._lock:
            record = self._records.get(job_id)
            task = self._tasks.get(job_id)

        if record is None:
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
            self._deferred_releases.discard(job_id)

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


    def _make_record(self, job_id: ULID, submitted_at: datetime) -> JobRecord:
        """Create the record for a newly submitted job; override to use a JobRecord subclass."""
        return JobRecord(id=job_id, status=JobStatus.pending, submitted_at=submitted_at)

    async def _on_job_result(self, record: JobRecord, result: Any) -> None:
        """Handle a successful job result on the live record, before its status becomes completed."""
        return None

    async def _runner(self, job_id: ULID, target: JobTarget, execute_target: JobExecutor) -> Any:
        """Acquire a capacity slot and run the job, handling cancellation that arrives while queued."""
        try:
            await self._limiter.acquire()
        except asyncio.CancelledError:
            # The target never ran; close an unstarted coroutine to avoid a "never awaited" warning.
            if inspect.iscoroutine(target):
                target.close()

            async with self._lock:
                record = self._records.get(job_id)

                if record is not None:
                    record.status = JobStatus.canceled
                    record.finished_at = datetime.now(timezone.utc)

            raise

        return await self._run_with_state(job_id, execute_target)

    async def _run_with_state(
        self,
        job_id: ULID,
        execute_target: JobExecutor,
    ) -> Any:
        """Run a job whose capacity slot is already held and manage its state transitions."""
        release_capacity = True

        try:
            async with self._lock:
                record = self._records[job_id]
                record.status = JobStatus.running
                record.started_at = datetime.now(timezone.utc)

            try:
                result = await execute_target()

            except asyncio.CancelledError:
                async with self._lock:
                    release_capacity = job_id not in self._deferred_releases
                    record = self._records[job_id]

                    if release_capacity:
                        record.status = JobStatus.canceled
                        record.finished_at = datetime.now(timezone.utc)
                    elif record.status is not JobStatus.canceled:
                        record.status = JobStatus.canceling

                raise

            except Exception as error:
                error_traceback = traceback.format_exc()
                # Extract clean error message (exception type and message only)
                error_lines = error_traceback.strip().split("\n")
                clean_error = error_lines[-1] if error_lines else str(error)

                async with self._lock:
                    record = self._records[job_id]
                    record.status = JobStatus.failed
                    record.finished_at = datetime.now(timezone.utc)
                    record.error = clean_error
                    record.error_traceback = error_traceback

                raise

            async with self._lock:
                record = self._records[job_id]

            await self._on_job_result(record, result)

            async with self._lock:
                record.status = JobStatus.completed
                record.finished_at = datetime.now(timezone.utc)
                self._results[job_id] = result

            return result

        finally:
            if release_capacity:
                self._limiter.release()

    async def _execute_target(
        self,
        job_id: ULID,
        target: JobTarget,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a job target, running synchronous callables in the default executor."""
        if inspect.isawaitable(target):
            if args or kwargs:
                # Close the coroutine to avoid "coroutine was never awaited" warning
                if inspect.iscoroutine(target):
                    target.close()
                raise TypeError("Args/kwargs not supported when target is an awaitable object.")
            return await target

        if inspect.iscoroutinefunction(target):
            return await target(*args, **kwargs)

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, functools.partial(target, *args, **kwargs))

        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if not future.done():
                # A running thread cannot be interrupted: keep the capacity slot until it finishes.
                self._defer_capacity_release(job_id, future)
            raise

    def _defer_capacity_release(self, job_id: ULID, future: asyncio.Future[Any]) -> None:
        """Hold a canceled sync job's capacity slot until its worker thread actually finishes."""
        self._deferred_releases.add(job_id)

        def _on_thread_finished(_: asyncio.Future[Any]) -> None:
            task = asyncio.ensure_future(self._finalize_deferred_cancellation(job_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        future.add_done_callback(_on_thread_finished)

    async def _finalize_deferred_cancellation(self, job_id: ULID) -> None:
        """Mark a canceling job as canceled and release its capacity once its thread has finished."""
        async with self._lock:
            record = self._records.get(job_id)

            if record is not None:
                record.status = JobStatus.canceled
                record.finished_at = datetime.now(timezone.utc)

        self._limiter.release()

    def _drain(self, task: asyncio.Task[Any]) -> None:
        """Observe a finished job task so its outcome is never reported as unretrieved."""
        if task.cancelled():
            return

        task.exception()
