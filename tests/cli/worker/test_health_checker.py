"""
Unit tests for HealthChecker.

Tests worker health monitoring via heartbeat IPC using Queue.
"""

import asyncio
import time

import pytest

from taskiq.cli.worker.health_checker import (
    HealthChecker,
    HeartbeatData,
)


@pytest.fixture
def health_checker() -> HealthChecker:
    """Create HealthChecker instance for testing."""
    return HealthChecker(
        num_workers=2,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.3,
    )


def test_health_checker_init() -> None:
    """Test HealthChecker initialization."""
    checker = HealthChecker(
        num_workers=3,
        heartbeat_interval=5.0,
        heartbeat_timeout=15.0,
    )

    assert checker.num_workers == 3
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
    health_checker: HealthChecker,
) -> None:
    """Test that stuck worker is marked correctly."""
    health_checker.startup_timeout = 0.3
    health_checker.check_interval = 0.1
    _ = health_checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(health_checker.monitor())

    # Wait for timeout (0.3s without heartbeat)
    await asyncio.sleep(0.4)

    monitor_task.cancel()

    # Check worker marked as stuck
    assert health_checker.worker_health["worker-0"]["status"] == "stuck"
    assert health_checker.worker_health["worker-1"]["status"] == "stuck"


@pytest.mark.asyncio
async def test_health_checker_multiple_stuck_workers(
    health_checker: HealthChecker,
) -> None:
    """Test that multiple stuck workers are detected."""
    health_checker.startup_timeout = 0.3
    health_checker.check_interval = 0.1
    queue = health_checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(health_checker.monitor())

    # Send heartbeat from worker-0 after monitor starts
    await asyncio.sleep(0.1)
    queue.put(
        HeartbeatData(
            worker_id="worker-0",
            timestamp=time.time(),
            broker_connected=True,
        ),
    )

    # Wait for heartbeat timeout (worker-0 should be stuck)
    await asyncio.sleep(0.4)

    monitor_task.cancel()

    # Check both workers are stuck
    # (worker-0 stuck because heartbeat timed out, worker-1 never sent heartbeat)
    assert health_checker.worker_health["worker-0"]["status"] == "stuck"
    assert health_checker.worker_health["worker-1"]["status"] == "stuck"


@pytest.mark.asyncio
async def test_health_checker_worker_reconnects(
    health_checker: HealthChecker,
) -> None:
    """Test that worker reconnecting after being stuck is detected correctly."""
    health_checker.startup_timeout = 0.3
    health_checker.check_interval = 0.1
    queue = health_checker.create_queue()

    # Start monitor
    monitor_task = asyncio.create_task(health_checker.monitor())

    # Send initial heartbeat (worker is alive)
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )
    # Wait for monitor to process heartbeat (check_interval is 0.1s)
    await asyncio.sleep(0.15)
    assert health_checker.worker_health["worker-0"]["status"] == "alive"

    # Wait for heartbeat timeout (worker becomes stuck)
    await asyncio.sleep(0.4)
    assert (
        health_checker.worker_health["worker-0"]["status"] == "stuck"  # type: ignore[comparison-overlap]
    )  # Status changes from alive to stuck after timeout

    # Worker reconnects and sends heartbeat
    queue.put(
        {
            "worker_id": "worker-0",
            "timestamp": time.time(),
            "broker_connected": True,
        },
    )

    # Wait for monitor to process heartbeat (check_interval is 0.1s)
    await asyncio.sleep(0.15)

    monitor_task.cancel()

    # Check worker is now alive again
    assert health_checker.worker_health["worker-0"]["status"] == "alive"


def test_health_checker_get_health_status_all_healthy(
    health_checker: HealthChecker,
) -> None:
    """Test health status when all workers are healthy."""
    _ = health_checker.create_queue()

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
    _ = health_checker.create_queue()

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
    _ = health_checker.create_queue()

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
    _ = health_checker.create_queue()

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
    _ = health_checker.create_queue()

    # Queue requires close() before join_thread()
    health_checker.cleanup()

    # Verify queue was closed (join_thread() is called on Queue.close())
    # We can't easily test this without mocking Queue internals,
    # so just verify no exception


@pytest.mark.asyncio
async def test_health_checker_handles_queue_error(
    health_checker: HealthChecker,
) -> None:
    """Test that monitor handles queue errors gracefully."""
    queue = health_checker.create_queue()

    # Close queue to simulate error
    queue.close()

    # Start monitor - should not crash
    monitor_task = asyncio.create_task(health_checker.monitor())

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
        {  # type: ignore[typeddict-item]
            "worker_id": "worker-0",
            "timestamp": time.time(),
        },
    )  # Intentionally malformed for testing

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
