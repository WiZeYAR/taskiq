"""
Integration test for health check with actual worker processes.

This test reproduces the heartbeat flow to verify workers send heartbeats
through pipes to the health checker.
"""

import asyncio
import json
import time
from multiprocessing import Pipe, Process

import pytest

from taskiq.cli.worker.health_checker import HealthChecker
from taskiq.cli.worker.health_server import HealthHTTPServer
from unittest.mock import MagicMock


def worker_target(
    args_dict: dict,
    health_pipe,
) -> None:
    """
    Simulated worker function that sends heartbeats.

    This mimics what taskiq/cli/worker/run.py does.
    """
    from multiprocessing import current_process
    import time
    import asyncio

    # Simulate worker startup
    proc_name = current_process().name
    print(f"[{proc_name}] Worker starting with health_pipe: {health_pipe is not None}")

    if health_pipe:
        async def send_heartbeat() -> None:
            """Send periodic health heartbeats."""
            count = 0
            while True:
                try:
                    health_pipe.send({
                        "worker_id": proc_name,
                        "timestamp": time.time(),
                        "broker_connected": True,
                    })
                    count += 1
                    print(f"[{proc_name}] Sent heartbeat #{count}")
                except Exception as e:
                    print(f"[{proc_name}] Heartbeat error: {e}")
                    break
                await asyncio.sleep(1)  # 1 second interval for testing

        # Run heartbeat task
        asyncio.run(send_heartbeat())
    else:
        print(f"[{proc_name}] No health pipe provided")
        # Simulate work
        time.sleep(5)


def test_worker_sends_heartbeat_via_pipe_sync() -> None:
    """
    Test that a simulated worker sends heartbeats through pipe.

    This is a synchronous test to verify pipe communication works.
    """
    reader, writer = Pipe(duplex=False)

    # Start simulated worker in process
    proc = Process(
        target=worker_target,
        kwargs={"args_dict": {}, "health_pipe": writer},
        name="test-worker-0",
        daemon=True,
    )
    proc.start()

    # Read heartbeats from pipe
    received = []
    timeout = time.time() + 5  # 5 second timeout

    while time.time() < timeout:
        if reader.poll():
            try:
                data = reader.recv()
                received.append(data)
                print(f"[Main] Received heartbeat: {data}")
                if len(received) >= 2:  # Got 2 heartbeats
                    break
            except Exception as e:
                print(f"[Main] Read error: {e}")
                break
        time.sleep(0.1)

    # Cleanup
    proc.terminate()
    proc.join(timeout=2)

    # Verify heartbeats were received
    assert len(received) >= 1, f"Expected at least 1 heartbeat, got {len(received)}"
    assert received[0]["worker_id"] == "test-worker-0"
    assert received[0]["broker_connected"] is True


def test_health_checker_receives_worker_heartbeats() -> None:
    """
    Test that HealthChecker receives heartbeats from worker process.

    This tests the pipe communication between worker and HealthChecker.
    """
    action_queue = MagicMock()
    checker = HealthChecker(
        num_workers=1,
        action_queue=action_queue,
        heartbeat_interval=1.0,
        heartbeat_timeout=3.0,
        check_interval=0.1,
    )

    # Create pipe
    writers = checker.create_pipes()
    assert len(writers) == 1

    # Start worker that sends heartbeats
    proc = Process(
        target=worker_target,
        kwargs={"args_dict": {}, "health_pipe": writers[0]},
        name="test-worker-0",
        daemon=True,
    )
    proc.start()

    # Wait for heartbeats to be processed
    time.sleep(3)

    # Check health status
    status = checker.get_health_status()
    print(f"Health status: {status}")

    # Cleanup
    proc.terminate()
    proc.join(timeout=2)
    checker.cleanup()

    # Verify worker is detected as alive
    assert status["status"] == "healthy", f"Expected 'healthy', got '{status['status']}'"
    assert status["workers"]["alive"] == 1, f"Expected 1 alive worker, got {status['workers']['alive']}"
    assert status["workers"]["stuck"] == 0
