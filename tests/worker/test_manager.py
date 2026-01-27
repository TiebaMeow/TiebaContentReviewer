import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tiebameow.schemas.rules import ReviewRule

from src.worker.manager import WorkerManager


@pytest.fixture
def mock_deps():
    return {
        "repository": MagicMock(),
        "dispatcher": MagicMock(),
        "matcher": MagicMock(),
        "redis": MagicMock(),
    }


@pytest.fixture
def manager(mock_deps):
    return WorkerManager(
        mock_deps["repository"],
        mock_deps["dispatcher"],
        mock_deps["matcher"],
        mock_deps["redis"],
        stream_key="test:stream",
    )


@pytest.mark.asyncio
async def test_manager_start_stop(manager):
    # Mock loop to just return
    manager._loop = AsyncMock()

    await manager.start()
    assert manager._running is True
    assert manager._manage_task is not None

    await manager.stop()
    assert manager._running is False
    # manager._manage_task.cancel() is called


@pytest.mark.asyncio
async def test_reconcile_workers_add(manager, mock_deps):
    # Setup repo to return rules for FID 100
    rule = MagicMock(spec=ReviewRule)
    rule.fid = 100
    mock_deps["repository"].get_active_rules.return_value = [rule]

    # Mock ReviewWorker class
    with patch("src.worker.manager.ReviewWorker") as mock_worker_class:
        mock_worker_instance = MagicMock()
        mock_worker_instance.run = AsyncMock()
        mock_worker_instance.stop = MagicMock()
        mock_worker_class.return_value = mock_worker_instance

        await manager._reconcile_workers()

        # Check worker created
        assert 100 in manager._active_workers
        assert len(manager._active_workers) == 1

        # Check constructor call
        mock_worker_class.assert_called_once()
        _, kwargs = mock_worker_class.call_args
        assert kwargs["fid"] == 100
        assert kwargs["stream_key"] == "test:stream:100"

        # Check run task created
        assert manager._active_workers[100][1] is not None


@pytest.mark.asyncio
async def test_reconcile_workers_remove(manager, mock_deps):
    # Setup existing worker for FID 100
    mock_worker = MagicMock()
    mock_worker.stop = MagicMock()
    mock_task = MagicMock()

    manager._active_workers[100] = (mock_worker, mock_task)

    # Setup repo to return NO rules
    mock_deps["repository"].get_active_rules.return_value = []

    await manager._reconcile_workers()

    # Check worker removed
    assert 100 not in manager._active_workers
    assert len(manager._active_workers) == 0

    # Check cleanup
    mock_worker.stop.assert_called_once()
    mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_reconcile_workers_no_change(manager, mock_deps):
    # Setup existing worker for FID 100
    mock_worker = MagicMock()
    mock_task = MagicMock()
    manager._active_workers[100] = (mock_worker, mock_task)

    # Setup repo to return rules for FID 100
    rule = MagicMock(spec=ReviewRule)
    rule.fid = 100
    mock_deps["repository"].get_active_rules.return_value = [rule]

    await manager._reconcile_workers()

    # Should be no change
    assert 100 in manager._active_workers
    assert len(manager._active_workers) == 1
    assert manager._active_workers[100] == (mock_worker, mock_task)


@pytest.mark.asyncio
async def test_manager_loop_error(manager):
    # Mock reconcile raising Exception then CancelledError to exit loop
    manager._reconcile_workers = AsyncMock(side_effect=[Exception("Loop Error"), asyncio.CancelledError])

    with patch("asyncio.sleep", AsyncMock()):  # skip sleep
        manager._running = True
        # Run _loop directly (await it)
        try:
            await manager._loop()
        except asyncio.CancelledError:
            pass

    # Verify called
    assert manager._reconcile_workers.call_count == 2


@pytest.mark.asyncio
async def test_manager_stop_waiting(manager):
    # Setup a worker
    mock_worker = MagicMock()
    # Task that is cancellable
    stop_event = asyncio.Event()

    # When worker.stop() is called, set the event to wake up the dummy task
    mock_worker.stop.side_effect = stop_event.set

    async def dummy_task():
        try:
            # Wait for stop signal with a small timeout just in case
            await asyncio.wait_for(stop_event.wait(), timeout=10)
        except asyncio.CancelledError:
            pass  # catch cancel
        except TimeoutError:
            pass  # Should not happen if stop is called

    task = asyncio.create_task(dummy_task())
    manager._active_workers[100] = (mock_worker, task)
    manager._manage_task = MagicMock()  # Mock manage task

    manager._running = True

    await manager.stop()

    mock_worker.stop.assert_called_once()
    assert task.done()
    assert len(manager._active_workers) == 0


@pytest.mark.asyncio
async def test_manager_stop_cleanup(manager):
    # Setup active workers
    mock_worker = MagicMock()
    mock_worker.stop = MagicMock()

    # Create a real task to be awaited
    async def dummy_task():
        pass

    task = asyncio.create_task(dummy_task())

    manager._active_workers[100] = (mock_worker, task)
    manager._running = True

    await manager.stop()

    assert len(manager._active_workers) == 0
    mock_worker.stop.assert_called_once()
    assert task.done()
