"""Tests for job scheduler functionality."""

import asyncio
import gc
import threading
import warnings
from datetime import datetime

import pytest
import ulid
from pydantic import ValidationError

from servicekit import InMemoryScheduler, JobStatus
from servicekit.schemas import JobRecord

ULID = ulid.ULID


class TestInMemoryScheduler:
    """Test InMemoryScheduler functionality."""

    @pytest.mark.asyncio
    async def test_add_simple_async_job(self) -> None:
        """Test adding and executing a simple async job."""
        scheduler = InMemoryScheduler()

        async def simple_task():
            await asyncio.sleep(0.01)
            return "done"

        job_id = await scheduler.add_job(simple_task)
        assert isinstance(job_id, ULID)

        # Wait for completion
        await scheduler.wait(job_id)

        # Check status and result
        status = await scheduler.get_status(job_id)
        assert status == JobStatus.completed

        result = await scheduler.get_result(job_id)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_add_sync_job(self) -> None:
        """Test adding a synchronous callable (runs in thread pool)."""
        scheduler = InMemoryScheduler()

        def sync_task():
            return 42

        job_id = await scheduler.add_job(sync_task)
        await scheduler.wait(job_id)

        result = await scheduler.get_result(job_id)
        assert result == 42

    @pytest.mark.asyncio
    async def test_job_with_args_kwargs(self) -> None:
        """Test job with positional and keyword arguments."""
        scheduler = InMemoryScheduler()

        async def task_with_args(a: int, b: int, c: int = 10) -> int:
            return a + b + c

        job_id = await scheduler.add_job(task_with_args, 1, 2, c=3)
        await scheduler.wait(job_id)

        result = await scheduler.get_result(job_id)
        assert result == 6

    @pytest.mark.asyncio
    async def test_job_lifecycle_states(self) -> None:
        """Test job progresses through states: pending -> running -> completed."""
        scheduler = InMemoryScheduler()

        async def slow_task():
            await asyncio.sleep(0.05)
            return "result"

        job_id = await scheduler.add_job(slow_task)

        # Initially pending (may already be running due to async scheduling)
        record = await scheduler.get_record(job_id)
        assert record.status in (JobStatus.pending, JobStatus.running)
        assert record.submitted_at is not None

        # Wait and check completed
        await scheduler.wait(job_id)
        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.completed
        assert record.started_at is not None
        assert record.finished_at is not None
        assert record.error is None

    @pytest.mark.asyncio
    async def test_job_failure_with_traceback(self) -> None:
        """Test job failure captures error traceback."""
        scheduler = InMemoryScheduler()

        async def failing_task():
            raise ValueError("Something went wrong")

        job_id = await scheduler.add_job(failing_task)

        # Wait for task to complete (will fail)
        try:
            await scheduler.wait(job_id)
        except ValueError:
            pass  # Expected

        # Check status and error
        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.failed
        assert record.error is not None
        assert "ValueError" in record.error
        assert "Something went wrong" in record.error

        # Getting result should raise RuntimeError with traceback
        with pytest.raises(RuntimeError, match="ValueError"):
            await scheduler.get_result(job_id)

    @pytest.mark.asyncio
    async def test_cancel_running_job(self) -> None:
        """Test canceling a running job."""
        scheduler = InMemoryScheduler()

        async def long_task():
            await asyncio.sleep(10)  # Long enough to cancel
            return "never reached"

        job_id = await scheduler.add_job(long_task)
        await asyncio.sleep(0.01)  # Let it start

        # Cancel the job
        was_canceled = await scheduler.cancel(job_id)
        assert was_canceled is True

        # Check status
        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.canceled

    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_false(self) -> None:
        """Test canceling already completed job returns False."""
        scheduler = InMemoryScheduler()

        async def quick_task():
            return "done"

        job_id = await scheduler.add_job(quick_task)
        await scheduler.wait(job_id)

        # Try to cancel completed job
        was_canceled = await scheduler.cancel(job_id)
        assert was_canceled is False

    @pytest.mark.asyncio
    async def test_delete_job(self) -> None:
        """Test deleting a job removes all records."""
        scheduler = InMemoryScheduler()

        async def task():
            return "result"

        job_id = await scheduler.add_job(task)
        await scheduler.wait(job_id)

        # Delete job
        await scheduler.delete(job_id)

        # Job should no longer exist
        with pytest.raises(KeyError):
            await scheduler.get_record(job_id)

    @pytest.mark.asyncio
    async def test_delete_running_job_cancels_it(self) -> None:
        """Test deleting running job cancels it first."""
        scheduler = InMemoryScheduler()

        async def long_task():
            await asyncio.sleep(10)
            return "never"

        job_id = await scheduler.add_job(long_task)
        await asyncio.sleep(0.01)  # Let it start

        # Delete while running
        await scheduler.delete(job_id)

        # Job should be gone
        with pytest.raises(KeyError):
            await scheduler.get_record(job_id)

    @pytest.mark.asyncio
    async def test_get_all_records_sorted_newest_first(self) -> None:
        """Test get_all_records returns jobs sorted by submission time."""
        scheduler = InMemoryScheduler()

        async def task():
            return "done"

        job_ids = []
        for _ in range(3):
            jid = await scheduler.add_job(task)
            job_ids.append(jid)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        records = await scheduler.get_all_records()
        assert len(records) == 3

        # Should be newest first
        assert records[0].id == job_ids[2]
        assert records[1].id == job_ids[1]
        assert records[2].id == job_ids[0]

    @pytest.mark.asyncio
    async def test_max_concurrency_limits_parallel_execution(self) -> None:
        """Test max_concurrency limits concurrent job execution."""
        scheduler = InMemoryScheduler(max_concurrency=2)

        running_count = 0
        max_concurrent = 0

        async def concurrent_task():
            nonlocal running_count, max_concurrent
            running_count += 1
            max_concurrent = max(max_concurrent, running_count)
            await asyncio.sleep(0.05)
            running_count -= 1
            return "done"

        # Schedule 5 jobs
        job_ids = [await scheduler.add_job(concurrent_task) for _ in range(5)]

        # Wait for all to complete
        await asyncio.gather(*[scheduler.wait(jid) for jid in job_ids])

        # At most 2 should have run concurrently
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_set_max_concurrency_runtime(self) -> None:
        """Test changing max_concurrency at runtime."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        assert scheduler.max_concurrency == 1

        await scheduler.set_max_concurrency(5)
        assert scheduler.max_concurrency == 5

        await scheduler.set_max_concurrency(None)
        assert scheduler.max_concurrency is None

    @pytest.mark.asyncio
    async def test_job_not_found_raises_key_error(self) -> None:
        """Test accessing non-existent job raises KeyError."""
        scheduler = InMemoryScheduler()
        fake_id = ULID()

        with pytest.raises(KeyError):
            await scheduler.get_record(fake_id)

        with pytest.raises(KeyError):
            await scheduler.get_status(fake_id)

        with pytest.raises(KeyError):
            await scheduler.get_result(fake_id)

        with pytest.raises(KeyError):
            await scheduler.cancel(fake_id)

        with pytest.raises(KeyError):
            await scheduler.delete(fake_id)

    @pytest.mark.asyncio
    async def test_get_result_before_completion_raises(self) -> None:
        """Test get_result raises if job not finished."""
        scheduler = InMemoryScheduler()

        async def slow_task():
            await asyncio.sleep(1)
            return "done"

        job_id = await scheduler.add_job(slow_task)

        # Try to get result immediately (job is pending/running)
        with pytest.raises(RuntimeError, match="not finished"):
            await scheduler.get_result(job_id)

        # Cleanup
        await scheduler.cancel(job_id)

    @pytest.mark.asyncio
    async def test_wait_timeout(self) -> None:
        """Test wait with timeout raises asyncio.TimeoutError."""
        scheduler = InMemoryScheduler()

        async def long_task():
            await asyncio.sleep(10)
            return "never"

        job_id = await scheduler.add_job(long_task)

        with pytest.raises(asyncio.TimeoutError):
            await scheduler.wait(job_id, timeout=0.01)

        # Cleanup
        await scheduler.cancel(job_id)

    @pytest.mark.asyncio
    async def test_awaitable_target(self) -> None:
        """Test passing an already-created awaitable as target."""
        scheduler = InMemoryScheduler()

        async def task():
            return "result"

        # Create coroutine object
        coro = task()

        job_id = await scheduler.add_job(coro)
        await scheduler.wait(job_id)

        result = await scheduler.get_result(job_id)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_awaitable_target_rejects_args(self) -> None:
        """Test awaitable target raises TypeError if args/kwargs provided."""
        scheduler = InMemoryScheduler()

        async def task():
            return "result"

        coro = task()

        job_id = await scheduler.add_job(coro, "extra_arg")
        # The error happens during execution, not during add_job
        with pytest.raises(TypeError, match="Args/kwargs not supported"):
            await scheduler.wait(job_id)


class TestSchedulerShutdown:
    """Tests for scheduler shutdown and draining."""

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_running_jobs(self) -> None:
        """Test shutdown lets a short job finish within the timeout."""
        scheduler = InMemoryScheduler()

        async def quick() -> str:
            await asyncio.sleep(0.01)
            return "done"

        job_id = await scheduler.add_job(quick)
        await scheduler.shutdown(timeout=5.0)

        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.completed

    @pytest.mark.asyncio
    async def test_shutdown_cancels_long_running_jobs(self) -> None:
        """Test shutdown cancels jobs that outlast the timeout."""
        scheduler = InMemoryScheduler()

        async def slow() -> None:
            await asyncio.sleep(60)

        job_id = await scheduler.add_job(slow)
        await scheduler.shutdown(timeout=0.01)

        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.canceled

    @pytest.mark.asyncio
    async def test_shutdown_zero_timeout_cancels_immediately(self) -> None:
        """Test shutdown with a zero timeout cancels without waiting."""
        scheduler = InMemoryScheduler()

        async def slow() -> None:
            await asyncio.sleep(60)

        job_id = await scheduler.add_job(slow)
        await asyncio.sleep(0.01)
        await scheduler.shutdown(timeout=0)

        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.canceled

    @pytest.mark.asyncio
    async def test_add_job_after_shutdown_raises(self) -> None:
        """Test add_job is rejected once the scheduler is shut down."""
        scheduler = InMemoryScheduler()
        await scheduler.shutdown()

        async def noop() -> None:
            return None

        with pytest.raises(RuntimeError, match="Scheduler is shut down"):
            await scheduler.add_job(noop)

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        """Test shutdown can be called twice without error."""
        scheduler = InMemoryScheduler()
        await scheduler.shutdown()
        await scheduler.shutdown(timeout=0.01)


class TestSchedulerCancellation:
    """Test cancellation semantics for queued, async, and synchronous jobs."""

    @pytest.mark.asyncio
    async def test_cancel_queued_job_marks_it_canceled(self) -> None:
        """Test canceling a job queued behind max_concurrency marks it canceled with finished_at."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        release_first = asyncio.Event()

        async def blocking_task() -> str:
            await release_first.wait()
            return "first"

        async def queued_task() -> str:
            return "second"

        first_id = await scheduler.add_job(blocking_task)
        await asyncio.sleep(0.01)
        queued_id = await scheduler.add_job(queued_task)
        await asyncio.sleep(0.01)

        assert (await scheduler.get_status(queued_id)) == JobStatus.pending

        was_canceled = await scheduler.cancel(queued_id)
        assert was_canceled is True

        record = await scheduler.get_record(queued_id)
        assert record.status == JobStatus.canceled
        assert record.finished_at is not None

        release_first.set()
        await scheduler.wait(first_id)

    @pytest.mark.asyncio
    async def test_cancel_immediately_after_add_job(self) -> None:
        """Test canceling before the job ran any step still reaches a terminal state."""
        scheduler = InMemoryScheduler()

        async def never_runs() -> str:
            return "never"

        job_id = await scheduler.add_job(never_runs)
        was_canceled = await scheduler.cancel(job_id)
        assert was_canceled is True

        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.canceled
        assert record.finished_at is not None

    @pytest.mark.asyncio
    async def test_cancel_before_first_step_closes_coroutine_target(self) -> None:
        """Test canceling before the runner ever executed closes the coroutine target quietly."""
        scheduler = InMemoryScheduler()

        async def never_runs() -> str:
            return "never"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            coroutine_target = never_runs()
            job_id = await scheduler.add_job(coroutine_target)
            assert (await scheduler.cancel(job_id)) is True

            del coroutine_target
            gc.collect()

        assert [warning for warning in caught if "never awaited" in str(warning.message)] == []

        record = await scheduler.get_record(job_id)
        assert record.status == JobStatus.canceled
        assert record.finished_at is not None

    @pytest.mark.asyncio
    async def test_cancel_queued_coroutine_target_emits_no_warning(self) -> None:
        """Test a coroutine object canceled while queued is closed instead of warning."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        release_first = asyncio.Event()

        async def blocking_task() -> str:
            await release_first.wait()
            return "first"

        async def queued_task() -> str:
            return "second"

        first_id = await scheduler.add_job(blocking_task)
        await asyncio.sleep(0.01)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            coroutine_target = queued_task()
            queued_id = await scheduler.add_job(coroutine_target)
            await asyncio.sleep(0.01)
            await scheduler.cancel(queued_id)

            del coroutine_target
            gc.collect()

        assert [warning for warning in caught if "never awaited" in str(warning.message)] == []

        release_first.set()
        await scheduler.wait(first_id)

    @pytest.mark.asyncio
    async def test_cancellation_does_not_reach_loop_exception_handler(self) -> None:
        """Test canceling running and queued jobs never invokes the loop exception handler."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        handled: list[dict[str, object]] = []

        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: handled.append(context))

        try:

            async def long_task() -> str:
                await asyncio.sleep(10)
                return "never"

            running_id = await scheduler.add_job(long_task)
            queued_id = await scheduler.add_job(long_task)
            await asyncio.sleep(0.01)

            await scheduler.cancel(queued_id)
            await scheduler.cancel(running_id)
            await asyncio.sleep(0.01)
            gc.collect()
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        assert handled == []

    @pytest.mark.asyncio
    async def test_cancel_sync_job_holds_capacity_until_thread_finishes(self) -> None:
        """Test canceling a blocking sync job reports canceling and keeps its capacity slot."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        thread_release = threading.Event()
        second_started = asyncio.Event()

        def blocking_sync_task() -> str:
            thread_release.wait(timeout=10)
            return "first"

        async def second_task() -> str:
            second_started.set()
            return "second"

        first_id = await scheduler.add_job(blocking_sync_task)
        await asyncio.sleep(0.05)
        assert (await scheduler.get_status(first_id)) == JobStatus.running

        was_canceled = await scheduler.cancel(first_id)
        assert was_canceled is True
        assert (await scheduler.get_status(first_id)) == JobStatus.canceling

        second_id = await scheduler.add_job(second_task)
        await asyncio.sleep(0.05)

        assert not second_started.is_set()
        assert (await scheduler.get_status(second_id)) == JobStatus.pending

        thread_release.set()
        await scheduler.wait(second_id)

        first_record = await scheduler.get_record(first_id)
        assert first_record.status == JobStatus.canceled
        assert first_record.finished_at is not None
        assert (await scheduler.get_result(second_id)) == "second"

    @pytest.mark.asyncio
    async def test_delete_canceling_sync_job_releases_capacity_once(self) -> None:
        """Test deleting a job whose sync thread is still running frees capacity exactly once."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        thread_release = threading.Event()

        def blocking_sync_task() -> str:
            thread_release.wait(timeout=10)
            return "first"

        async def follow_up_task() -> str:
            return "second"

        first_id = await scheduler.add_job(blocking_sync_task)
        await asyncio.sleep(0.05)

        await scheduler.delete(first_id)

        with pytest.raises(KeyError):
            await scheduler.get_record(first_id)

        thread_release.set()
        second_id = await scheduler.add_job(follow_up_task)
        await scheduler.wait(second_id)
        assert (await scheduler.get_result(second_id)) == "second"


class TestSchedulerCapacityLimit:
    """Test the resizable concurrency limit."""

    @pytest.mark.asyncio
    async def test_raising_limit_starts_exactly_one_queued_job(self) -> None:
        """Test raising the limit from 1 to 2 admits exactly one queued job."""
        scheduler = InMemoryScheduler(max_concurrency=1)
        release_all = asyncio.Event()
        started = 0

        async def tracked_task() -> str:
            nonlocal started
            started += 1
            await release_all.wait()
            return "done"

        job_ids = [await scheduler.add_job(tracked_task) for _ in range(3)]
        await asyncio.sleep(0.02)
        assert started == 1

        await scheduler.set_max_concurrency(2)
        await asyncio.sleep(0.02)
        assert started == 2

        await scheduler.set_max_concurrency(1)
        await asyncio.sleep(0.02)
        assert started == 2

        release_all.set()
        await asyncio.gather(*[scheduler.wait(job_id) for job_id in job_ids])
        assert started == 3

    @pytest.mark.asyncio
    async def test_set_max_concurrency_rejects_non_positive(self) -> None:
        """Test set_max_concurrency raises ValueError for zero and negative limits."""
        scheduler = InMemoryScheduler()

        with pytest.raises(ValueError):
            await scheduler.set_max_concurrency(0)

        with pytest.raises(ValueError):
            await scheduler.set_max_concurrency(-1)

        assert scheduler.max_concurrency is None

    def test_constructor_rejects_zero_max_concurrency(self) -> None:
        """Test constructing a scheduler with max_concurrency=0 fails validation."""
        with pytest.raises(ValidationError):
            InMemoryScheduler(max_concurrency=0)


class TestSchedulerSubclassHooks:
    """Test the protected extension hooks for subclasses."""

    @pytest.mark.asyncio
    async def test_make_record_and_on_job_result_hooks(self) -> None:
        """Test a subclass can supply its own record type and post-process results."""

        class TaggedJobRecord(JobRecord):
            """Job record carrying the value a job returned."""

            returned_value: str | None = None

        observed_statuses: list[JobStatus] = []

        class TaggedScheduler(InMemoryScheduler):
            """Scheduler storing the job result on a custom record type."""

            def _make_record(self, job_id: ULID, submitted_at: datetime) -> JobRecord:
                """Create a TaggedJobRecord for the job."""
                return TaggedJobRecord(id=job_id, status=JobStatus.pending, submitted_at=submitted_at)

            async def _on_job_result(self, record: JobRecord, result: object) -> None:
                """Store the result on the record before its status becomes completed."""
                assert isinstance(record, TaggedJobRecord)
                observed_statuses.append(record.status)
                record.returned_value = str(result)

        scheduler = TaggedScheduler()

        async def task() -> str:
            return "payload"

        job_id = await scheduler.add_job(task)
        await scheduler.wait(job_id)

        record = await scheduler.get_record(job_id)
        assert isinstance(record, TaggedJobRecord)
        assert record.returned_value == "payload"
        assert record.status == JobStatus.completed
        assert observed_statuses == [JobStatus.running]
