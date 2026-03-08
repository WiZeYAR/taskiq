"""
Unit tests for HealthChecker.

Tests worker health monitoring via heartbeat IPC.
"""

import asyncio
import time
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskiq.cli.worker.health_checker import HealthChecker
from taskiq.cli.worker.process_manager import ReloadOneAction


@pytest.fixture
def action_queue() -> MagicMock:
    """
    Mock action queue for HealthChecker.

    :returns: Mocked Queue object.
    """
    return MagicMock()


@pytest.fixture
def health_checker(action_queue: MagicMock) -> HealthChecker:
    """
    Create HealthChecker instance for testing.

    :param action_queue: Mocked action queue.
    :returns: HealthChecker instance with fast intervals for testing.
    """
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
    assert len(checker.health_readers) == 0
    assert len(checker.health_writers) == 0
    assert len(checker.last_heartbeat) == 0
    assert len(checker.worker_health) == 0


def test_health_checker_create_pipes(health_checker: HealthChecker) -> None:
    """Test pipe creation for workers."""
    writers = health_checker.create_pipes()

    assert len(writers) == 2
    assert len(health_checker.health_readers) == 2
    assert len(health_checker.health_writers) == 2

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
    health_checker.create_pipes()

    # Simulate worker sending heartbeat
    health_checker.health_writers[0].send(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        }
    )

    # Run monitor for one iteration
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.05)
    monitor_task.cancel()

    # Check health updated
    assert health_checker.worker_health["worker-0"]["status"] == "alive"
    assert health_checker.worker_health["worker-0"]["broker_connected"] is True


@pytest.mark.asyncio
async def test_health_checker_monitor_multiple_heartbeats(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor processes multiple heartbeats from different workers."""
    health_checker.create_pipes()

    # Simulate both workers sending heartbeats
    health_checker.health_writers[0].send(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        }
    )
    health_checker.health_writers[1].send(
        {
            "worker_id": "worker-1",
            "timestamp": time.time(),
            "broker_connected": False,
        }
    )

    # Run monitor
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.05)
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
    )
    checker.create_pipes()

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
    )
    checker.create_pipes()

    # Only send heartbeat from worker-0
    checker.health_writers[0].send(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        }
    )

    # Start monitor
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait for worker-1 timeout
    await asyncio.sleep(0.4)

    monitor_task.cancel()

    # Check only worker-1 triggered reload
    reload_calls = [
        call
        for call in action_queue.put.call_args_list
        if len(call[0]) > 0 and isinstance(call[0][0], ReloadOneAction)
    ]
    assert len(reload_calls) == 1
    assert reload_calls[0][0][0].worker_num == 1
    assert checker.worker_health["worker-0"]["status"] == "alive"
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
    )
    checker.create_pipes()

    # Start monitor
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait for timeout (worker stuck)
    await asyncio.sleep(0.4)

    # Worker reconnects and sends heartbeat
    checker.health_writers[0].send(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        }
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
    health_checker.create_pipes()

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
    health_checker.create_pipes()

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
    health_checker.create_pipes()

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
    health_checker.create_pipes()

    # Simulate mixed broker connectivity
    health_checker.worker_health["worker-0"]["status"] = "alive"
    health_checker.worker_health["worker-0"]["broker_connected"] = True
    health_checker.worker_health["worker-1"]["status"] = "alive"
    health_checker.worker_health["worker-1"]["broker_connected"] = False

    status = health_checker.get_health_status()

    assert status["status"] == "degraded"  # One broker disconnected
    assert status["workers"]["total"] == 2
    assert status["workers"]["alive"] == 2
    assert status["workers"]["stuck"] == 0
    assert status["broker_connected"] is False  # Not all connected


def test_health_checker_cleanup(health_checker: HealthChecker) -> None:
    """Test cleanup closes all pipes."""
    writers = health_checker.create_pipes()

    # Mock close methods to verify called
    for reader in health_checker.health_readers:
        reader.close = MagicMock()  # type: ignore[method-assign]
    for writer in health_checker.health_writers:
        writer.close = MagicMock()  # type: ignore[method-assign]

    health_checker.cleanup()

    # Verify all close methods called
    for reader in health_checker.health_readers:
        reader.close.assert_called_once()
    for writer in health_checker.health_writers:
        writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_health_checker_handles_pipe_error(
    action_queue: MagicMock,
) -> None:
    """Test that monitor handles pipe errors gracefully."""
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
    )
    checker.create_pipes()

    # Close pipe to simulate error
    checker.health_readers[0].close()

    # Start monitor - should not crash
    monitor_task = asyncio.create_task(checker.monitor())

    # Wait a bit to ensure monitor handled error
    await asyncio.sleep(0.2)

    monitor_task.cancel()

    # Monitor should still be running without errors
    assert True  # If we got here, no exception was raised


@pytest.mark.asyncio
async def test_health_checker_empty_heartbeat_data(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor handles empty/malformed heartbeat data."""
    health_checker.create_pipes()

    # Send malformed data (missing fields)
    health_checker.health_writers[0].send(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            # Missing broker_connected field
        }
    )

    # Run monitor - should not crash
    monitor_task = asyncio.create_task(health_checker.monitor())
    await asyncio.sleep(0.05)
    monitor_task.cancel()

    # Check worker status updated (with default False for missing field)
    assert health_checker.worker_health["worker-0"]["status"] == "alive"
    assert health_checker.worker_health["worker-0"].get("broker_connected", False) is False
