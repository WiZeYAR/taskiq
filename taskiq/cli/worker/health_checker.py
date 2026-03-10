"""
Health check monitoring for worker subprocesses.

Monitors worker health via heartbeat IPC using multiprocessing pipes.
Detects worker crashes, stuck processes, and broker disconnections.
"""

import asyncio
import logging
import time
from contextlib import suppress
from multiprocessing import Pipe
from typing import Any

logger = logging.getLogger("taskiq.health-checker")


class HealthChecker:
    """
    Monitor worker health via heartbeat IPC.

    Detects:
    - Worker crashes (handled by ProcessManager.is_alive())
    - Worker stuck (via heartbeat timeout)
    - Broker disconnected (via heartbeat data)

    :param num_workers: Number of worker subprocesses.
    :param action_queue: Queue for sending reload actions to ProcessManager.
    :param heartbeat_interval: Seconds between heartbeats from workers.
    :param heartbeat_timeout: Seconds before worker considered stuck (3x interval).
    :param startup_timeout: Seconds to wait for first heartbeat before stuck.
    :param check_interval: Seconds between health checks (for testing).
    """

    def __init__(
        self,
        num_workers: int,
        action_queue: Any,
        heartbeat_interval: float = 5.0,
        heartbeat_timeout: float = 15.0,
        startup_timeout: float = 0.0,
        check_interval: float = 0.1,
    ) -> None:
        self.num_workers = num_workers
        self.action_queue = action_queue
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.startup_timeout = startup_timeout
        self.check_interval = check_interval

        self.health_readers: list[Any] = []
        self.health_writers: list[Any] = []
        self.last_heartbeat: dict[str, float | None] = {}
        self.worker_health: dict[str, dict] = {}
        self.reloads_pending: set[str] = set()

    def create_pipes(self) -> list[Any]:
        """
        Create pipe pairs for each worker.

        Each worker gets a pipe writer to send heartbeats.
        HealthChecker keeps readers to receive heartbeats.

        :returns: List of pipe writers to pass to worker subprocesses.
        """
        writers = []
        for i in range(self.num_workers):
            reader, writer = Pipe(duplex=False)
            self.health_readers.append(reader)
            self.health_writers.append(writer)
            writers.append(writer)

            # Initialize tracking for this worker
            worker_name = f"worker-{i}"
            self.last_heartbeat[worker_name] = None
            self.worker_health[worker_name] = {
                "worker_id": worker_name,
                "status": "unknown",
                "broker_connected": False,
                "last_heartbeat": None,
                "initialized_at": time.time(),
            }

        return writers

    async def monitor(self) -> None:
        """
        Background task that monitors worker heartbeats.

        Reads heartbeats from pipes, updates health status,
        and triggers restarts for stuck workers.
        """
        # Import at runtime to avoid circular import
        from taskiq.cli.worker.process_manager import ReloadOneAction  # noqa: PLC0415

        while True:
            for _i, reader in enumerate(self.health_readers):
                while reader.poll():  # Read all pending messages
                    try:
                        data = reader.recv()
                        worker_name = data["worker_id"]
                        self.last_heartbeat[worker_name] = data["timestamp"]
                        self.reloads_pending.discard(worker_name)
                        self.worker_health[worker_name].update(
                            {
                                "status": "alive",
                                "broker_connected": data.get(
                                    "broker_connected",
                                    False,
                                ),
                                "last_heartbeat": data["timestamp"],
                            },
                        )
                    except (EOFError, OSError):
                        # Worker died, keep last known state
                        pass

            # Check for stuck workers
            now = time.time()
            for i in range(self.num_workers):
                worker_name = f"worker-{i}"
                last_seen = self.last_heartbeat.get(worker_name)

                if last_seen is not None:
                    if now - last_seen > self.heartbeat_timeout:
                        msg = (
                            f"{worker_name} is stuck "
                            f"(no heartbeat for {now - last_seen:.1f}s)"
                        )
                        logger.warning(msg)
                        self.worker_health[worker_name]["status"] = "stuck"

                        if worker_name not in self.reloads_pending:
                            self.reloads_pending.add(worker_name)
                            self.action_queue.put(
                                ReloadOneAction(worker_num=i, is_reload_all=False),
                            )
                elif self.startup_timeout > 0:
                    initialized_at = self.worker_health[worker_name].get(
                        "initialized_at",
                        now,
                    )
                    if now - initialized_at > self.startup_timeout:
                        logger.warning(
                            f"{worker_name} failed to send initial heartbeat",
                        )
                        self.worker_health[worker_name]["status"] = "stuck"

                        if worker_name not in self.reloads_pending:
                            self.reloads_pending.add(worker_name)
                            self.action_queue.put(
                                ReloadOneAction(worker_num=i, is_reload_all=False),
                            )

            await asyncio.sleep(self.check_interval)

    def get_health_status(self) -> dict:
        """
        Get current health status for HTTP server.

        :returns: Health summary with worker counts and details.
        """
        alive_count = sum(
            1 for health in self.worker_health.values() if health["status"] == "alive"
        )
        stuck_count = sum(
            1 for health in self.worker_health.values() if health["status"] == "stuck"
        )
        broker_connected = all(
            health["broker_connected"] for health in self.worker_health.values()
        )

        return {
            "status": (
                "healthy" if stuck_count == 0 and broker_connected else "degraded"
            ),
            "workers": {
                "total": self.num_workers,
                "alive": alive_count,
                "stuck": stuck_count,
            },
            "broker_connected": broker_connected,
            "workers_detail": list(self.worker_health.values()),
        }

    def cleanup(self) -> None:
        """Close all pipe connections."""
        for reader in self.health_readers:
            with suppress(OSError):
                reader.close()
        for writer in self.health_writers:
            with suppress(OSError):
                writer.close()
