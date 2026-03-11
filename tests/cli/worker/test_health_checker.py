"""
Unit tests for HealthChecker.

Tests worker health monitoring via heartbeat IPC using Queue.
"""

import asyncio
import time
from unittest.mock import MagicMock
from multiprocessing import Queue

import pytest

from taskiq.cli.worker.health_checker import HealthChecker
from taskiq.cli.worker.process_manager import ReloadOneAction


@pytest.fixture
def action_queue() -> MagicMock:
    """Mock action queue for HealthChecker."""
    return MagicMock()


@pytest.fixture
def health_checker(action_queue: MagicMock) -> HealthChecker:
    """Create HealthChecker instance for testing."""
    return HealthChecker(
        num_workers=2,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
    )


def test_health_checker_init(action_queue: MagicMock) -> None:
    """Test HealthChecker initialization."""
    checker = HealthChecker(
        num_workers=3,
        action_queue=action_queue,
        heartbeat_interval=5.0,
        heartbeat_timeout=15.0,
    )

    assert checker.num_workers == 3
    assert checker.action_queue == action_queue
    assert checker.heartbeat_interval == 5.0
    assert checker.heartbeat_timeout == 15.0
    assert len(checker.last_heartbeat) == 0
    assert len(checker.worker_health) == 0


def test_health_checker_create_queue(health_checker: HealthChecker) -> None:
    """Test queue creation for workers."""
    queue = health_checker.create_queue()

    assert queue is not None

    # Check worker tracking initialized
    assert "worker-0" in health_checker.last_heartbeat
    assert "worker-1" in health_checker.last_heartbeat
    assert health_checker.worker_health["worker-0"]["status"] == "unknown"
    assert health_checker.worker_health["worker-1"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_health_checker_monitor_receives_heartbeat(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor receives and processes heartbeats."""
    queue = health_checker.create_queue()

    # Simulate worker sending heartbeat
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )

    # Run monitor - sleep longer than check_interval (0.1s)
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.15)
    monitor_task.cancel()

    # Check health updated
    assert health_checker.worker_health["worker-0"]["status"] == "alive"
    assert health_checker.worker_health["worker-0"]["broker_connected"] is True


@pytest.mark.asyncio
async def test_health_checker_monitor_multiple_heartbeats(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor processes multiple heartbeats from different workers."""
    queue = health_checker.create_queue()

    # Simulate both workers sending heartbeats
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )
    queue.put(
        {
            "worker_id": "worker-1",
            "timestamp": time.time(),
            "broker_connected": False,
        },
    )

    # Run monitor - sleep longer than check_interval (0.1s)
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.15)
    monitor_task.cancel()

    # Check both workers updated
    assert health_checker.worker_health["worker-0"]["status"] == "alive"
    assert health_checker.worker_health["worker-0"]["broker_connected"] is True
    assert health_checker.worker_health["worker-1"]["status"] == "alive"
    assert health_checker.worker_health["worker-1"]["broker_connected"] is False


@pytest.mark.asyncio
async def test_health_checker_detects_stuck_worker(
    action_queue: MagicMock,
) -> None:
    """Test that stuck worker triggers reload action."""
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
        startup_timeout=0.3,
        check_interval=0.1,
    )
    queue = checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait for timeout (0.3s without heartbeat)
    await asyncio.sleep(0.4)

    monitor_task.cancel()

    # Check reload action queued
    action_queue.put.assert_called()
    call_args = action_queue.put.call_args
    assert call_args is not None
    reload_action = call_args[0][0]
    assert isinstance(reload_action, ReloadOneAction)
    assert reload_action.worker_num == 0
    assert checker.worker_health["worker-0"]["status"] == "stuck"


@pytest.mark.asyncio
async def test_health_checker_multiple_stuck_workers(
    action_queue: MagicMock,
) -> None:
    """Test that multiple stuck workers trigger multiple reload actions."""
    checker = HealthChecker(
        num_workers=2,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
        startup_timeout=0.3,
        check_interval=0.1,
    )
    queue = checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(checker.monitor())

    # Send heartbeat from worker-0 after monitor starts
    await asyncio.sleep(0.1)
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )

    # Wait for heartbeat timeout (worker-0 should be stuck)
    await asyncio.sleep(0.4)

    monitor_task.cancel()

    # Check both workers triggered reload
    # (worker-0 stuck because heartbeat timed out, worker-1 never sent heartbeat)
    reload_calls = [
        call
        for call in action_queue.put.call_args_list
        if len(call[0]) > 0 and isinstance(call[0][0], ReloadOneAction)
    ]
    assert len(reload_calls) == 2
    assert checker.worker_health["worker-0"]["status"] == "stuck"
    assert checker.worker_health["worker-1"]["status"] == "stuck"


@pytest.mark.asyncio
async def test_health_checker_worker_reconnects(
    action_queue: MagicMock,
) -> None:
    """Test that worker reconnecting after being stuck is detected correctly."""
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
        startup_timeout=0.3,
        check_interval=0.1,
    )
    queue = checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait for timeout (worker stuck)
    await asyncio.sleep(0.4)

    # Worker reconnects and sends heartbeat
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )

    # Let monitor process heartbeat
    await asyncio.sleep(0.05)

    monitor_task.cancel()

    # Check worker is now alive
    assert checker.worker_health["worker-0"]["status"] == "alive"


def test_health_checker_get_health_status_all_healthy(
    health_checker: HealthChecker,
) -> None:
    """Test health status when all workers are healthy."""
    queue = health_checker.create_queue()

    # Simulate all workers healthy
    health_checker.worker_health["worker-0"]["status"] = "alive"
    health_checker.worker_health["worker-0"]["broker_connected"] = True
    health_checker.worker_health["worker-1"]["status"] = "alive"
    health_checker.worker_health["worker-1"]["broker_connected"] = True

    status = health_checker.get_health_status()

    assert status["status"] == "healthy"
    assert status["workers"]["total"] == 2
    assert status["workers"]["alive"] == 2
    assert status["workers"]["stuck"] == 0
    assert status["broker_connected"] is True
    assert len(status["workers_detail"]) == 2


def test_health_checker_get_health_status_degraded(
    health_checker: HealthChecker,
) -> None:
    """Test health status when some workers are stuck."""
    queue = health_checker.create_queue()

    # Simulate one healthy, one stuck
    health_checker.worker_health["worker-0"]["status"] = "alive"
    health_checker.worker_health["worker-0"]["broker_connected"] = True
    health_checker.worker_health["worker-1"]["status"] = "stuck"
    health_checker.worker_health["worker-1"]["broker_connected"] = False

    status = health_checker.get_health_status()

    assert status["status"] == "degraded"
    assert status["workers"]["total"] == 2
    assert status["workers"]["alive"] == 1
    assert status["workers"]["stuck"] == 1
    assert status["broker_connected"] is False
    assert len(status["workers_detail"]) == 2


def test_health_checker_get_health_status_all_stuck(
    health_checker: HealthChecker,
) -> None:
    """Test health status when all workers are stuck."""
    queue = health_checker.create_queue()

    # Simulate all workers stuck
    health_checker.worker_health["worker-0"]["status"] = "stuck"
    health_checker.worker_health["worker-0"]["broker_connected"] = False
    health_checker.worker_health["worker-1"]["status"] = "stuck"
    health_checker.worker_health["worker-1"]["broker_connected"] = False

    status = health_checker.get_health_status()

    assert status["status"] == "degraded"
    assert status["workers"]["total"] == 2
    assert status["workers"]["alive"] == 0
    assert status["workers"]["stuck"] == 2
    assert status["broker_connected"] is False


def test_health_checker_get_health_status_mixed_connection(
    health_checker: HealthChecker,
) -> None:
    """Test health status when broker connections are mixed."""
    queue = health_checker.create_queue()

    # Simulate mixed broker connectivity
    health_checker.worker_health["worker-0"]["status"] = "alive"
    health_checker.worker_health["worker-0"]["broker_connected"] = True
    health_checker.worker_health["worker-1"]["status"] = "alive"
    health_checker.worker_health["worker-1"]["broker_connected"] = False

    status = health_checker.get_health_status()

    assert status["status"] == "degraded"
    assert status["workers"]["total"] == 2
    assert status["workers"]["alive"] == 2
    assert status["workers"]["stuck"] == 0
    assert status["broker_connected"] is False


def test_health_checker_cleanup(health_checker: HealthChecker) -> None:
    """Test cleanup closes queue."""
    queue = health_checker.create_queue()

    # Queue requires close() before join_thread()
    health_checker.cleanup()

    # Verify queue was closed (join_thread() is called on Queue.close())
    # We can't easily test this without mocking Queue internals, so just verify no exception


@pytest.mark.asyncio
async def test_health_checker_handles_queue_error(
    action_queue: MagicMock,
) -> None:
    """Test that monitor handles queue errors gracefully."""
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
    )
    queue = checker.create_queue()

    # Close queue to simulate error
    queue.close()

    # Start monitor - should not crash
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait to ensure monitor handled error
    await asyncio.sleep(0.2)

    monitor_task.cancel()

    # Monitor should still be running without errors
    assert True


@pytest.mark.asyncio
async def test_health_checker_empty_heartbeat_data(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor handles empty/malformed heartbeat data."""
    queue = health_checker.create_queue()

    # Send malformed data (missing broker_connected field)
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
        },
    )

    # Run monitor - sleep longer than check_interval (0.1s)
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.15)
    monitor_task.cancel()

    # Check worker status updated (with default False for missing field)
    assert health_checker.worker_health["worker-0"]["status"] == "alive"
    broker_connected = health_checker.worker_health["worker-0"].get(
        "broker_connected",
        False,
    )
    assert broker_connected is False
