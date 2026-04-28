"""
Health check monitoring for worker subprocesses.

Monitors worker health via heartbeat IPC using multiprocessing pipes.
Detects worker crashes, stuck processes, and broker disconnections.
"""

import asyncio
import logging
import time
from multiprocessing import Queue
from typing import Any, Literal, NoReturn, Protocol, TypedDict, cast

logger = logging.getLogger("taskiq.health-checker")


class MiddlewareHealthDetail(TypedDict):
    """
    Health status for a single middleware.

    Collected from middleware.health() method for each worker.
    """

    middleware_name: str
    is_healthy: bool
    data: dict[str, Any]


class HeartbeatData(TypedDict):
    """
    Heartbeat message from worker to HealthChecker.

    Sent via multiprocessing.Queue for health monitoring.
    """

    worker_id: str
    timestamp: float
    broker_connected: bool
    middleware_health: dict[str, MiddlewareHealthDetail]


class WorkerHealthDetail(TypedDict):
    """
    Detailed health status for a single worker.

    Stored in HealthChecker.worker_health dictionary.
    """

    worker_id: str
    status: Literal["unknown", "alive", "stuck"]
    broker_connected: bool
    last_heartbeat: float | None
    initialized_at: float


class WorkerCounts(TypedDict):
    """Summary counts of worker states."""

    total: int
    alive: int
    stuck: int


class HealthStatus(TypedDict):
    """
    Overall health status for HTTP API response.

    Returned by HealthChecker.get_health_status() and
    consumed by HealthHTTPServer.
    """

    status: Literal["healthy", "degraded"]
    workers: WorkerCounts
    broker_connected: bool
    workers_detail: list[WorkerHealthDetail]
    middleware_health: dict[str, dict[str, MiddlewareHealthDetail]]


class HealthQueue(Protocol):
    """
    Type-safe protocol for health queue.

    Wraps multiprocessing.Queue with typed methods for heartbeats.
    All workers send HeartbeatData messages to this queue.
    """

    def put(self, data: HeartbeatData) -> None:
        """Put a heartbeat message into the queue."""
        ...

    def get_nowait(self) -> HeartbeatData:
        """Get a message from the queue without blocking."""
        ...

    def empty(self) -> bool:
        """Check if the queue is empty."""
        ...

    def close(self) -> None:
        """Close the queue."""
        ...

    def join_thread(self) -> None:
        """Join the queue's background thread."""
        ...


class HealthChecker:
    """
    Monitor worker health via heartbeat IPC.

    Detects:
    - Worker crashes (handled by ProcessManager.is_alive())
    - Worker stuck (via heartbeat timeout)
    - Broker disconnected (via heartbeat data)
    - Middleware unhealthy (via middleware health checks)

    :param num_workers: Number of worker subprocesses.
    :param heartbeat_interval: Seconds between heartbeats from workers.
    :param heartbeat_timeout: Seconds before worker considered stuck (3x interval).
    :param startup_timeout: Seconds to wait for first heartbeat before stuck.
    :param check_interval: Seconds between health checks (for testing).
    """

    def __init__(
        self,
        num_workers: int,
        heartbeat_interval: float = 5.0,
        heartbeat_timeout: float = 15.0,
        startup_timeout: float = 0.0,
        check_interval: float = 0.1,
    ) -> None:
        self.num_workers = num_workers
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.startup_timeout = startup_timeout
        self.check_interval = check_interval

        self.health_queue: HealthQueue | None = None
        self.last_heartbeat: dict[str, float | None] = {}
        self.worker_health: dict[str, WorkerHealthDetail] = {}
        self.middleware_health: dict[str, dict[str, MiddlewareHealthDetail]] = {}

    def create_queue(self) -> HealthQueue:
        """
        Create shared queue for all workers to send heartbeats.

        All workers send heartbeats to the same queue.
        HealthChecker reads from the queue to monitor all workers.

        :returns: Queue for workers to send heartbeats.
        """
        logger.info("Creating shared health queue for %d workers", self.num_workers)
        self.health_queue = cast(HealthQueue, Queue())

        for i in range(self.num_workers):
            worker_name = f"worker-{i}"
            self.last_heartbeat[worker_name] = None
            self.worker_health[worker_name] = WorkerHealthDetail(
                worker_id=worker_name,
                status="unknown",
                broker_connected=False,
                last_heartbeat=None,
                initialized_at=time.time(),
            )
            logger.debug("Initialized health tracking for %s", worker_name)

        logger.info("Created shared health queue")
        return self.health_queue

    def reset_worker(self, worker_id: str) -> None:
        """
        Reset health state for a worker after respawn.

        :param worker_id: Worker identifier (e.g. 'worker-0').
        """
        self.last_heartbeat[worker_id] = None
        self.middleware_health.pop(worker_id, None)
        if worker_id in self.worker_health:
            self.worker_health[worker_id] = WorkerHealthDetail(
                worker_id=worker_id,
                status="unknown",
                broker_connected=False,
                last_heartbeat=None,
                initialized_at=time.time(),
            )
            logger.info("Reset health state for %s", worker_id)

    def _process_heartbeat_data(self, data: HeartbeatData) -> None:
        """
        Process a single heartbeat message from a worker.

        :param data: Heartbeat data dictionary.
        """
        worker_name = data["worker_id"]
        self.last_heartbeat[worker_name] = data["timestamp"]
        self.worker_health[worker_name]["status"] = "alive"
        self.worker_health[worker_name]["broker_connected"] = data.get(
            "broker_connected",
            False,
        )
        self.worker_health[worker_name]["last_heartbeat"] = data["timestamp"]

        middleware_health = data.get("middleware_health", {})
        if middleware_health:
            self._update_worker_middleware_health(worker_name, middleware_health)

        logger.debug(
            "Received heartbeat from %s at %s (broker_connected: %s)",
            worker_name,
            data["timestamp"],
            data.get("broker_connected", False),
        )

    def _check_stuck_workers(self, now: float) -> None:
        """
        Check for stuck workers and update their status.

        :param now: Current timestamp.
        """
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

    def _update_worker_middleware_health(
        self,
        worker_id: str,
        middleware_health: dict[str, MiddlewareHealthDetail],
    ) -> None:
        """
        Update middleware health data for a worker.

        If any middleware is unhealthy, mark the worker as stuck.

        :param worker_id: Worker identifier.
        :param middleware_health: Middleware health data from worker.
        """
        self.middleware_health[worker_id] = middleware_health

        any_unhealthy = any(not m["is_healthy"] for m in middleware_health.values())

        if any_unhealthy:
            self.worker_health[worker_id]["status"] = "stuck"
            logger.warning(
                "%s is stuck due to middleware health failure",
                worker_id,
            )

    async def monitor(self) -> NoReturn:
        """
        Background task that monitors worker heartbeats.

        Reads heartbeats from queue and updates health status.
        """
        logger.info("Health monitor started for %d workers", self.num_workers)

        while True:
            if self.health_queue is not None:
                while True:
                    try:
                        data = self.health_queue.get_nowait()
                        self._process_heartbeat_data(data)
                    except Exception:
                        break

            now = time.time()
            self._check_stuck_workers(now)

            await asyncio.sleep(self.check_interval)

    def get_health_status(self) -> HealthStatus:
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

        return HealthStatus(
            status=("healthy" if stuck_count == 0 and broker_connected else "degraded"),
            workers=WorkerCounts(
                total=self.num_workers,
                alive=alive_count,
                stuck=stuck_count,
            ),
            broker_connected=broker_connected,
            workers_detail=list(self.worker_health.values()),
            middleware_health=self.middleware_health,
        )

    def cleanup(self) -> None:
        """Close health queue."""
        if self.health_queue is not None:
            self.health_queue.close()
            self.health_queue.join_thread()
