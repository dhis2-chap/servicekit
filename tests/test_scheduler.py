"""Tests for job scheduler functionality."""

import asyncio

import pytest
import ulid

from servicekit import InMemoryScheduler, JobStatus

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
