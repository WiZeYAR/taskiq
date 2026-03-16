"""
Integration test for health check with actual worker processes.

This test reproduces heartbeat flow to verify workers send heartbeats
through Queue to health checker.
"""

import asyncio
import threading
import time
from multiprocessing import Process, Queue, current_process
from typing import Any
from unittest.mock import MagicMock

from taskiq.cli.worker.health_checker import HealthChecker


def worker_target(
    args_dict: dict[str, Any],
    health_queue: Any,
) -> None:
    """
    Simulated worker function that sends heartbeats.

    This mimics what taskiq/cli/worker/run.py does.
    """
    # Simulate worker startup
    proc_name = current_process().name

    if health_queue:

        async def send_heartbeat() -> None:
            """Send periodic health heartbeats."""
            count = 0
            while True:
                try:
                    health_queue.put(
                        {
                            "worker_id": proc_name,
                            "timestamp": time.time(),
                            "broker_connected": True,
                        },
                    )
                    count += 1
                except Exception:
                    break
                await asyncio.sleep(1)  # 1 second interval for testing

        # Run heartbeat task
        asyncio.run(send_heartbeat())
    else:
        # Simulate work
        time.sleep(5)


def test_worker_sends_heartbeat_via_queue_sync() -> None:
    """
    Test that a simulated worker sends heartbeats through Queue.

    This is a synchronous test to verify Queue communication works.
    """
    health_queue: Queue[dict[str, Any]] = Queue()

    # Start simulated worker in process
    proc = Process(
        target=worker_target,
        kwargs={"args_dict": {}, "health_queue": health_queue},
        name="worker-0",
        daemon=False,
    )
    proc.start()

    received = []
    timeout = time.time() + 10  # 10 second timeout
    last_heartbeat_time = None

    while time.time() < timeout:
        try:
            if not health_queue.empty():
                data = health_queue.get_nowait()
                received.append(data)
                last_heartbeat_time = time.time()
                if len(received) >= 2:  # Got 2 heartbeats
                    break

            # Check if worker is still alive
            if not proc.is_alive():
                break

            # If we got a heartbeat but haven't seen one in 5 seconds, stop
            if last_heartbeat_time and (time.time() - last_heartbeat_time) > 5:
                break

        except Exception:
            break
        time.sleep(0.1)

    # Cleanup
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2)
    else:
        proc.join(timeout=2)

    health_queue.close()

    # Verify heartbeats were received
    assert len(received) >= 1, f"Expected at least 1 heartbeat, got {len(received)}"
    assert received[0]["worker_id"] == "worker-0"
    assert received[0]["broker_connected"] is True


def test_health_checker_receives_worker_heartbeats() -> None:
    """
    Test that HealthChecker receives heartbeats from worker process.

    This tests Queue communication between worker and HealthChecker.
    """
    action_queue = MagicMock()
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=1.0,
        heartbeat_timeout=3.0,
        check_interval=0.1,
    )

    health_queue = checker.create_queue()
    assert health_queue is not None

    # Start HealthChecker monitor in background thread
    monitor_thread = threading.Thread(
        target=lambda: asyncio.run(checker.monitor()),
        daemon=True,
    )
    monitor_thread.start()
    time.sleep(0.2)  # Give monitor time to start

    # Start worker that sends heartbeats
    proc = Process(
        target=worker_target,
        kwargs={"args_dict": {}, "health_queue": health_queue},
        name="worker-0",  # Must match HealthChecker's naming scheme
        daemon=False,  # Non-daemon for proper cleanup
    )
    proc.start()

    # Wait for heartbeats to be processed
    time.sleep(3)

    # Check health status
    status = checker.get_health_status()

    # Cleanup
    proc.terminate()
    proc.join(timeout=2)
    checker.cleanup()

    # Verify worker is detected as alive
    assert (
        status["status"] == "healthy"
    ), f"Expected 'healthy', got '{status['status']}'"
    assert (
        status["workers"]["alive"] == 1
    ), f"Expected 1 alive worker, got {status['workers']['alive']}"
    assert status["workers"]["stuck"] == 0
