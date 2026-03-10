# HTTP-Based Healthchecks for TaskIQ Workers and Schedulers

**Status**: Planning Phase
**Date**: 2026-03-08
**Objective**: Design and implement optional HTTP-based healthcheck endpoints for taskiq workers and schedulers

---

## Executive Summary

This document outlines a comprehensive plan to add optional HTTP-based healthcheck endpoints to taskiq workers and schedulers. Healthchecks are essential for:

- **Container orchestration** (Kubernetes, Docker Swarm, etc.)
- **Load balancer health probes**
- **Monitoring and alerting** (Prometheus, Grafana, etc.)
- **Graceful deployment strategies** (rolling updates, blue-green deployments)

The proposed solution provides:
- **Optional** healthcheck HTTP server (enabled via configuration)
- **Multiple endpoints** for liveness, readiness, and detailed health status
- **Worker and scheduler** specific health information
- **Zero blocking** on main event loops (runs in background task)
- **Integration** with existing middleware and broker lifecycle hooks
- **Smart port selection** - Auto-selects available port in 17400-17499 range (avoids common port conflicts)

---

## Current State Analysis

### Existing Monitoring Infrastructure

TaskIQ currently has these monitoring capabilities:

#### 1. Prometheus Metrics (`taskiq/middlewares/prometheus_middleware.py`)
- **Purpose**: Expose metrics at `/metrics` endpoint
- **Implementation**: Uses `prometheus_client.start_http_server()` on port 9000
- **Only in workers**: Controlled by `is_worker_process` flag
- **Metrics provided**:
  - `received_tasks` counter
  - `found_errors` counter
  - `success_tasks` counter
  - `saved_results` counter
  - `execution_time` histogram

#### 2. Task Admin API (`taskiq/middlewares/taskiq_admin_middleware.py`)
- **Purpose**: HTTP client for sending task lifecycle events to external admin API
- **Endpoints called**:
  - `POST /api/tasks/{task_id}/queued`
  - `POST /api/tasks/{task_id}/started`
  - `POST /api/tasks/{task_id}/executed`
- **Implementation**: Uses `aiohttp.ClientSession` for HTTP communications

#### 3. Process Health Monitoring (`taskiq/cli/worker/process_manager.py`)
- **Purpose**: Internal process health monitoring
- **Mechanism**: Checks `worker.is_alive()` every second
- **Automatic recovery**: Restarts dead workers with configurable failure limits
- **No HTTP exposure**: Process health is internal only

### Missing Healthcheck Infrastructure

**No dedicated healthcheck implementations exist in taskiq codebase:**
- No `/health`, `/ready`, `/live` endpoints
- No health check module or directory
- No built-in HTTP server for health probes
- No readiness/liveness probe implementation
- No container orchestration integration

---

## Architecture Design

### Design Principles

1. **Optional by Default**: Healthcheck server must be opt-in to avoid breaking changes
2. **Non-Blocking**: HTTP server runs in background task, doesn't block main event loops
3. **Middleware-Based**: Leverage existing middleware system for lifecycle management
4. **Separate Endpoints**: Distinct liveness and readiness endpoints for best practices
5. **Extensible**: Support custom health checks via dependency injection
6. **Lightweight**: Minimal overhead, fast responses (<100ms target)
7. **Consistent**: Worker and scheduler use similar patterns
8. **Separation of Concerns**: Middleware orchestrates, Server implements, clear boundaries

### Component Overview

```
┌─────────────────────────────────────────────────────┐
│                    TaskIQ Worker/Scheduler          │
└─────────────────────────────────────────────────────┘
                              │
                              ├─► Broker (task execution/scheduling)
                              │
                              ├─► Middleware Pipeline
                              │   ├─ PrometheusMiddleware (existing)
                              │   └─ HealthcheckMiddleware (NEW - orchestrator)
                              │
                              └─► HealthcheckServer (NEW - implementation)
                                  ├─► GET /health (liveness)
                                  ├─► GET /ready (readiness)
                                  └─► GET /health/detailed (detailed status)
```

### Implementation Approach: Two-Class Architecture

**Decision**: Implement healthchecks as TWO separate classes:
1. **`HealthcheckMiddleware`** - Orchestrates lifecycle and integration
2. **`HealthcheckServer`** - Implements HTTP server and health check logic

**Rationale for Two-Class Approach**:

✅ **Follows Taskiq Patterns**:
   - PrometheusMiddleware orchestrates, `prometheus_client.start_http_server()` does the work
   - TaskiqAdminMiddleware orchestrates, `aiohttp.ClientSession` does the work
   - Middleware = integration layer, NOT full implementation

✅ **Separation of Concerns**:
   - Middleware: Taskiq lifecycle integration, configuration, broker access
   - Server: HTTP serving, health check logic, endpoint handlers
   - Clear boundaries, easier to understand and maintain

✅ **Testability**:
   - Test HTTP server independently without middleware setup
   - Test health check logic without HTTP server
   - Test middleware integration with mocked server

✅ **Reusability**:
   - `HealthcheckServer` could be used standalone (custom workers/schedulers)
   - Could be extended for custom health checks without touching middleware

✅ **Maintainability**:
   - Focused classes with single responsibilities
   - Easier to navigate and understand
   - Smaller files, less complexity per class

✅ **Custom Logic Requirements**:
   - Unlike PrometheusMiddleware (wraps external library)
   - We need taskiq-specific health checks (broker, receiver, scheduler loop)
   - Custom HTTP server implementation, not generic library wrapper
   - Worker vs scheduler specific logic

**User Experience**:
```python
# Users add ONE middleware
broker.add_middlewares(HealthcheckMiddleware(enabled=True, port=17500))

# Middleware creates and manages the server internally
# No need to think about servers directly
```

**Alternative (Single-Class) Considered**:
- Could put everything in one middleware class
- ❌ Larger, more complex middleware class
- ❌ Mixed concerns (lifecycle + HTTP + health checks)
- ❌ Server not independently testable
- ❌ Harder to extend for custom health checks

**Alternatives Not Chosen**:
- ❌ **Plugin system**: No existing plugin infrastructure for CLI commands
- ❌ **Built-in to worker/scheduler**: Too invasive, harder to make optional
- ❌ **Separate service**: Requires coordination, deployment complexity
- ❌ **Subclassing broker**: Limits broker choice, less flexible

---

## Healthcheck Endpoints Design

### 1. Liveness Endpoint (`GET /health`)

**Purpose**: Is the process running and not deadlocked?

**Response**: HTTP 200 OK if process is alive

**Worker Response**:
```json
{
  "status": "alive",
  "type": "worker",
  "process_id": 12345,
  "uptime_seconds": 3600.5
}
```

**Scheduler Response**:
```json
{
  "status": "alive",
  "type": "scheduler",
  "process_id": 12346,
  "uptime_seconds": 7200.2
}
```

**Failure**: HTTP 503 Service Unavailable (if server is shutting down)

**Status Codes**:
- `200 OK`: Process is alive and responding
- `503 Service Unavailable`: Process is shutting down

### 2. Readiness Endpoint (`GET /ready`)

**Purpose**: Is the process ready to accept work?

**Worker Response** (includes broker connectivity):
```json
{
  "status": "ready",
  "type": "worker",
  "checks": {
    "broker_connected": true,
    "receiver_initialized": true,
    "prefetch_queue_healthy": true
  }
}
```

**Scheduler Response** (includes schedule sources):
```json
{
  "status": "ready",
  "type": "scheduler",
  "checks": {
    "broker_connected": true,
    "schedule_sources_healthy": true,
    "sources_loaded": 3
  }
}
```

**Failure Scenarios**:
- Broker not connected: `{"status": "not_ready", "checks": {"broker_connected": false}}`
- Receiver not initialized: `{"status": "not_ready", "checks": {"receiver_initialized": false}}`
- Schedule sources failing: `{"status": "not_ready", "checks": {"schedule_sources_healthy": false}}`

**Status Codes**:
- `200 OK`: All checks passed, ready for work
- `503 Service Unavailable`: One or more checks failed

### 3. Detailed Health Endpoint (`GET /health/detailed`)

**Purpose**: Comprehensive health status for debugging and monitoring

**Worker Response**:
```json
{
  "status": "healthy",
  "type": "worker",
  "timestamp": "2026-03-08T11:00:00Z",
  "uptime_seconds": 3600.5,
  "process": {
    "pid": 12345,
    "max_async_tasks": 100,
    "current_async_tasks": 45,
    "prefetch_queue_size": 10,
    "max_prefetch": 20
  },
  "broker": {
    "connected": true,
    "type": "InMemoryBroker",
    "is_worker_process": true
  },
  "result_backend": {
    "connected": true,
    "type": "InmemoryResultBackend"
  },
  "checks": {
    "broker_connected": "pass",
    "receiver_initialized": "pass",
    "prefetch_queue_healthy": "pass",
    "result_backend_healthy": "pass"
  }
}
```

**Scheduler Response**:
```json
{
  "status": "healthy",
  "type": "scheduler",
  "timestamp": "2026-03-08T11:00:00Z",
  "uptime_seconds": 7200.2,
  "process": {
    "pid": 12346,
    "update_interval_seconds": 60,
    "loop_interval_seconds": 1
  },
  "broker": {
    "connected": true,
    "type": "InMemoryBroker",
    "is_scheduler_process": true
  },
  "schedule_sources": [
    {
      "source": "FileSystemScheduleSource",
      "status": "healthy",
      "schedules_count": 5,
      "last_update": "2026-03-08T10:59:00Z"
    }
  ],
  "next_runs": [
    {
      "task_name": "cleanup_job",
      "schedule_id": "cleanup-daily",
      "next_run": "2026-03-08T12:00:00Z",
      "seconds_until": 3600
    }
  ],
  "checks": {
    "broker_connected": "pass",
    "schedule_sources_healthy": "pass",
    "sources_loaded": "pass"
  }
}
```

**Status Codes**:
- `200 OK`: Detailed health information provided
- `503 Service Unavailable`: Critical system failure

---

## Worker Healthchecks

### Health Checks to Implement

#### 1. Broker Connectivity Check
```python
async def check_broker_connectivity(self) -> bool:
    """Check if broker is connected and operational."""
    try:
        # For in-memory broker, always connected
        if isinstance(self.broker, InMemoryBroker):
            return True

        # For network brokers, attempt connection check
        # This will be broker-specific
        return await self.broker.check_connection()
    except Exception:
        return False
```

#### 2. Receiver Initialization Check
```python
def check_receiver_initialized(self) -> bool:
    """Check if receiver is properly initialized."""
    return (
        hasattr(self, '_receiver')
        and self._receiver is not None
        and self._receiver.executor is not None
    )
```

#### 3. Prefetch Queue Health Check
```python
def check_prefetch_queue_health(self) -> bool:
    """Check if prefetch queue is not full/blocked."""
    if self._receiver.sem_prefetch is None:
        return True  # No prefetch, always healthy

    # Check if queue is accepting new items
    return not self._receiver.sem_prefetch.locked()
```

#### 4. Task Execution Stats
```python
def get_task_execution_stats(self) -> dict:
    """Get current task execution statistics."""
    if hasattr(self, '_receiver'):
        return {
            "max_async_tasks": self._receiver.max_async_tasks or "unlimited",
            "current_async_tasks": getattr(self._receiver, '_running_tasks_count', 0),
        }
    return {}
```

#### 5. Process Uptime
```python
def get_process_uptime(self) -> float:
    """Get process uptime in seconds."""
    return time.time() - self._start_time
```

### Worker-Specific Implementation Details

The worker healthcheck server needs to:

1. **Access receiver state** through broker or direct reference
2. **Monitor async task count** to detect overload conditions
3. **Check prefetch queue** to detect backpressure issues
4. **Report broker connection status** from broker's internal state
5. **Integrate with process manager** to report worker restarts

---

## Scheduler Healthchecks

### Health Checks to Implement

#### 1. Broker Connectivity Check
```python
async def check_broker_connectivity(self) -> bool:
    """Check if scheduler can dispatch tasks to broker."""
    try:
        # Similar to worker, but for scheduler mode
        return await self.broker.check_connection()
    except Exception:
        return False
```

#### 2. Schedule Sources Health Check
```python
async def check_schedule_sources_health(self) -> dict:
    """Check health of all schedule sources."""
    results = []
    for source in self.scheduler.sources:
        try:
            # Attempt to fetch schedules with timeout
            schedules = await asyncio.wait_for(
                source.get_schedules(),
                timeout=5.0
            )
            results.append({
                "source": type(source).__name__,
                "status": "healthy",
                "schedules_count": len(schedules),
                "last_update": datetime.now(tz=timezone.utc).isoformat()
            })
        except asyncio.TimeoutError:
            results.append({
                "source": type(source).__name__,
                "status": "timeout",
                "error": "Schedule source timed out"
            })
        except Exception as e:
            results.append({
                "source": type(source).__name__,
                "status": "error",
                "error": str(e)
            })
    return results
```

#### 3. Next Run Times
```python
def get_next_run_times(self) -> list[dict]:
    """Get next scheduled task runs."""
    next_runs = []
    now = datetime.now(tz=timezone.utc)

    for source, task_list in self.scheduler_loop.scheduled_tasks:
        for task in task_list:
            next_run = None

            if task.cron:
                # Calculate next cron execution
                # This is complex and requires pycron integration
                next_run = calculate_next_cron_run(task.cron, now)

            elif task.interval:
                # Calculate next interval execution
                last_run = self.scheduler_loop.interval_tasks_last_run.get(task.schedule_id)
                if last_run:
                    next_run = last_run + timedelta(seconds=task.interval)
                else:
                    next_run = now

            elif task.time:
                next_run = task.time

            if next_run and next_run > now:
                next_runs.append({
                    "task_name": task.task_name,
                    "schedule_id": task.schedule_id,
                    "next_run": next_run.isoformat(),
                    "seconds_until": (next_run - now).total_seconds()
                })

    # Sort and return top 5
    return sorted(next_runs, key=lambda x: x['seconds_until'])[:5]
```

#### 4. Scheduler Loop Status
```python
def get_scheduler_loop_status(self) -> dict:
    """Get scheduler loop status."""
    return {
        "update_interval_seconds": self.scheduler_loop.update_interval.total_seconds(),
        "loop_interval_seconds": self.scheduler_loop.loop_interval.total_seconds(),
        "schedules_loaded": len(self.scheduler_loop.scheduled_tasks),
        "last_schedule_update": self.scheduler_loop.scheduled_tasks_updated_at.isoformat()
    }
```

### Scheduler-Specific Implementation Details

The scheduler healthcheck server needs to:

1. **Access scheduler loop state** to report schedule status
2. **Monitor schedule sources** for health and timeout detection
3. **Calculate next run times** for monitoring and alerting
4. **Report broker connectivity** for task dispatch capability
5. **Detect schedule source failures** to prevent silent data loss

---

## Configuration Design

### Port Selection Strategy

**Problem**: Ports 8000-8001 are commonly used by:
- Development servers (Vue/React dev servers)
- API gateways and proxies
- Container services
- Load balancers and monitoring tools

**Solution**: Auto-select available port in range 17400-17499

**Rationale for 17400-17499 Range**:
- **High port range**: Avoids conflicts with common application ports (0-1023 system ports, 3000-9000 user ports)
- **IANA unassigned**: Not registered for specific services
- **Sufficient buffer**: 100 ports provide flexibility
- **Easy to remember**: Simple range, easy to spot in logs
- **Service differentiation**: Distinct from Prometheus metrics (port 9000)
- **Kubernetes friendly**: Service names can reference this range clearly

**Auto-Selection Algorithm**:
```python
# Worker: Start searching from 17400
# Scheduler: Start searching from 17450 (50-port buffer)
for port in range(17400, 17500):
    try:
        bind_socket(host, port)
        return port  # Found available port
    except OSError:
        continue  # Port in use, try next

raise RuntimeError("No available port found in 17400-17499")
```

**User Override**: Users can still explicitly specify any port:
```bash
# Auto-selection (recommended)
taskiq worker path.to.module:broker --healthcheck-enabled

# Explicit port
taskiq worker path.to.module:broker --healthcheck-enabled --healthcheck-port 17542
```

### Configuration Priority

### CLI Arguments

#### Worker Arguments (`taskiq/cli/worker/args.py`)

Add to `WorkerArgs` dataclass:

```python
@dataclass
class WorkerArgs:
    # ... existing fields ...

    # Healthcheck configuration
    healthcheck_enabled: bool = False
    healthcheck_port: int | None = None
    healthcheck_host: str = "0.0.0.0"
    healthcheck_path: str = "/health"
    healthcheck_detailed_path: str = "/health/detailed"
    healthcheck_readiness_path: str = "/ready"
```

**CLI Argument Definitions**:
```python
parser.add_argument(
    "--healthcheck-enabled",
    action="store_true",
    help="Enable healthcheck HTTP server for monitoring",
)
parser.add_argument(
    "--healthcheck-port",
    type=int,
    default=None,
    help="Port for healthcheck HTTP server (default: auto-selects available port 17400-17499)",
)
parser.add_argument(
    "--healthcheck-host",
    default="0.0.0.0",
    help="Host address for healthcheck server (default: 0.0.0.0)",
)
parser.add_argument(
    "--healthcheck-path",
    default="/health",
    help="Path for liveness endpoint (default: /health)",
)
parser.add_argument(
    "--healthcheck-detailed-path",
    default="/health/detailed",
    help="Path for detailed health endpoint (default: /health/detailed)",
)
parser.add_argument(
    "--healthcheck-readiness-path",
    default="/ready",
    help="Path for readiness endpoint (default: /ready)",
)
```

#### Scheduler Arguments (`taskiq/cli/scheduler/args.py`)

Add identical configuration to `SchedulerArgs` dataclass with same argument definitions.

**Port Selection Strategy**:
- **Auto-selection**: If `--healthcheck-port` is not specified, automatically find an available port in range 17400-17499
- **Worker**: Starts searching from 17400
- **Scheduler**: Starts searching from 17450 (50-port buffer)
- **Reasoning**: Ports 8000-8001 are commonly used (dev servers, proxies, etc.) and likely to conflict
- **User override**: Users can still explicitly specify any port via `--healthcheck-port`

#### Port Availability Checker

Implementation for auto-selecting available ports:

```python
import socket
from typing import Iterator

def find_available_port(
    start_port: int,
    max_attempts: int = 100,
    host: str = "0.0.0.0"
) -> int | None:
    """
    Find an available port starting from start_port.

    :param start_port: Port to start searching from
    :param max_attempts: Maximum number of ports to check
    :param host: Host to bind to
    :return: Available port or None if not found
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue
    return None
```

### Environment Variables

Support environment variables for container orchestration:

```bash
TASKIQ_HEALTHCHECK_ENABLED=true
TASKIQ_HEALTHCHECK_PORT=17500
TASKIQ_HEALTHCHECK_HOST=0.0.0.0
```

**Port Auto-Selection**:
- If `TASKIQ_HEALTHCHECK_PORT` is not set, auto-selects available port
- Worker: Search 17400-17499
- Scheduler: Search 17450-17499

### Configuration Priority

1. CLI arguments (highest priority)
2. Environment variables
3. Default values (lowest priority)

### Default Behavior

- **Disabled by default**: Healthcheck server only starts if explicitly enabled
- **No breaking changes**: Existing deployments continue to work
- **Opt-in required**: Users must add `--healthcheck-enabled` flag

### Port Strategy FAQ

**Q: Why 17400-17499 instead of 8000-8001?**
- Ports 8000-8001 are commonly used (dev servers, proxies, API gateways)
- High port ranges avoid conflicts with system and user applications
- 100-port buffer provides flexibility while keeping range memorable
- Kubernetes services can easily reference `taskiq-healthcheck` service

**Q: What if 17400-17499 is occupied?**
- The auto-selection algorithm tries 100 consecutive ports (17400-17499 for workers, 17450-17499 for schedulers)
- If all are occupied, startup fails with clear error message
- User can override with `--healthcheck-port` to use any port

**Q: How does Kubernetes handle auto-selected ports?**
- Use named ports in Kubernetes manifests (see deployment example below)
- Or use `TASKIQ_HEALTHCHECK_PORT` environment variable
- Kubernetes service will discover the actual port at runtime via Service object

**Q: What about Prometheus middleware on port 9000?**
- Healthchecks use different port range to avoid conflicts
- Both can run simultaneously without issues
- Clear separation: metrics (9000) vs healthchecks (17400-17499)

**Q: Can I use a different port range?**
- Yes, always specify explicit port with `--healthcheck-port`
- Environment variable: `TASKIQ_HEALTHCHECK_PORT=17542`
- This is recommended for production deployments where ports are managed centrally

---

## Implementation Steps

### Phase 1: Core Infrastructure

#### Step 1.1: Create Healthcheck Module
**File**: `taskiq/health/__init__.py`

Create new package for healthcheck functionality:

```python
"""
TaskIQ healthcheck server implementation.

Provides HTTP endpoints for liveness, readiness, and detailed health checks
for workers and schedulers.
"""

from taskiq.health.server import HealthcheckServer
from taskiq.health.middleware import HealthcheckMiddleware

__all__ = ["HealthcheckServer", "HealthcheckMiddleware"]
```

#### Step 1.2: Implement Port Availability Checker
**File**: `taskiq/health/utils.py`

Implement port availability utility:

```python
import socket
from logging import getLogger

logger = getLogger("taskiq.healthcheck")

def find_available_port(
    start_port: int,
    max_attempts: int = 100,
    host: str = "0.0.0.0",
) -> int | None:
    """
    Find an available port starting from start_port.

    :param start_port: Port to start searching from
    :param max_attempts: Maximum number of ports to check
    :param host: Host to bind to
    :return: Available port or None if not found
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                logger.debug(f"Found available port: {port}")
                return port
        except OSError:
            continue

    logger.error(
        f"No available port found in range {start_port}-{start_port + max_attempts}"
    )
    return None
```

#### Step 1.3: Implement HTTP Server
**File**: `taskiq/health/server.py`

Implement aiohttp-based HTTP server:

```python
import asyncio
from datetime import datetime, timezone
from logging import getLogger
from typing import Any

import aiohttp
from aiohttp import web

logger = getLogger("taskiq.healthcheck")

class HealthcheckServer:
    """
    HTTP server for healthcheck endpoints.

    Runs in background task to avoid blocking main event loops.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int | None = None,
        auto_select_port: bool = True,
        port_start_range: int = 17400,
        health_path: str = "/health",
        ready_path: str = "/ready",
        detailed_path: str = "/health/detailed",
    ) -> None:
        self.host = host
        self.port = port
        self.health_path = health_path
        self.ready_path = ready_path
        self.detailed_path = detailed_path
        self._server: aiohttp.web.Application | None = None
        self._runner: aiohttp.web.AppRunner | None = None
        self._site: aiohttp.web.TCPSite | None = None
        self._start_time = asyncio.get_event_loop().time()

        # Auto-select port if not specified
        if auto_select_port and port is None:
            from taskiq.health.utils import find_available_port
            self.port = find_available_port(port_start_range)
            if self.port is None:
                raise RuntimeError(
                    f"Could not find available port starting from {port_start_range}"
                )
            logger.info(f"Auto-selected healthcheck port: {self.port}")
        self.host = host
        self.port = port
        self.health_path = health_path
        self.ready_path = ready_path
        self.detailed_path = detailed_path
        self._server: aiohttp.web.Application | None = None
        self._runner: aiohttp.web.AppRunner | None = None
        self._site: aiohttp.web.TCPSite | None = None
        self._start_time = asyncio.get_event_loop().time()

    async def start(self) -> None:
        """Start healthcheck HTTP server."""
        app = web.Application()
        app.router.add_get(self.health_path, self._handle_health)
        app.router.add_get(self.ready_path, self._handle_ready)
        app.router.add_get(self.detailed_path, self._handle_detailed)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        self._server = app
        self._runner = runner
        self._site = site

        logger.info(
            f"Healthcheck server started on http://{self.host}:{self.port}"
        )

    async def stop(self) -> None:
        """Stop healthcheck HTTP server."""
        if self._site is not None:
            await self._site.stop()
        if self._runner is not None:
            await self._runner.cleanup()
        logger.info("Healthcheck server stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle liveness endpoint."""
        return web.json_response({
            "status": "alive",
            "type": self._get_type(),
            "process_id": os.getpid(),
            "uptime_seconds": self._get_uptime(),
        })

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """Handle readiness endpoint."""
        health_status = await self._check_readiness()
        return web.json_response(health_status)

    async def _handle_detailed(self, request: web.Request) -> web.Response:
        """Handle detailed health endpoint."""
        health_data = await self._get_detailed_health()
        return web.json_response(health_data)

    # ... helper methods for type, uptime, checks, etc.
```

#### Step 1.4: Implement Healthcheck Middleware
**File**: `taskiq/health/middleware.py`

```python
from taskiq.abc.middleware import TaskiqMiddleware
from taskiq.health.server import HealthcheckServer

class HealthcheckMiddleware(TaskiqMiddleware):
    """
    Middleware that starts healthcheck HTTP server.

    Provides liveness, readiness, and detailed health endpoints
    for worker and scheduler processes.
    """

    def __init__(
        self,
        enabled: bool = False,
        port: int | None = None,
        host: str = "0.0.0.0",
        health_path: str = "/health",
        ready_path: str = "/ready",
        detailed_path: str = "/health/detailed",
        # Auto-select port range based on worker/scheduler
        port_start_range: int = 17400,
    ) -> None:
        super().__init__()
        self.enabled = enabled
        self.port = port
        self.host = host
        self.health_path = health_path
        self.ready_path = ready_path
        self.detailed_path = detailed_path
        self._server: HealthcheckServer | None = None

    async def startup(self) -> None:
        """Start healthcheck server if enabled."""
        if not self.enabled:
            return

        if not self.broker.is_worker_process and not self.broker.is_scheduler_process:
            logger.info(
                "Healthcheck disabled for client processes (worker/scheduler mode only)"
            )
            return

        # Determine port start range based on type
        port_start = 17400
        if self.broker.is_scheduler_process:
            port_start = 17450  # Scheduler gets 50-port buffer

        self._server = HealthcheckServer(
            host=self.host,
            port=self.port,
            auto_select_port=True,  # Enable auto-selection
            port_start_range=port_start,
            health_path=self.health_path,
            ready_path=self.ready_path,
            detailed_path=self.detailed_path,
        )

        # Pass broker reference to server for health checks
        self._server.set_broker(self.broker)

        # Start server in background task
        asyncio.create_task(self._server.start())

    async def shutdown(self) -> None:
        """Stop healthcheck server."""
        if self._server is not None:
            await self._server.stop()
```

### Phase 2: Worker Integration

#### Step 2.1: Add CLI Arguments to WorkerArgs
**File**: `taskiq/cli/worker/args.py`

Add healthcheck configuration fields to dataclass and argument parser.

#### Step 2.2: Add Middleware to Worker Startup
**File**: `taskiq/cli/worker/run.py`

Modify `start_listen()` function:

```python
async def start_listen(args: WorkerArgs) -> None:
    # ... existing code ...

    # Add healthcheck middleware if enabled
    if args.healthcheck_enabled:
        health_middleware = HealthcheckMiddleware(
            enabled=True,
            port=args.healthcheck_port,
            host=args.healthcheck_host,
            health_path=args.healthcheck_path,
            ready_path=args.healthcheck_readiness_path,
            detailed_path=args.healthcheck_detailed_path,
        )
        broker.add_middlewares(health_middleware)

    # ... rest of existing code ...
```

#### Step 2.3: Implement Worker Health Checks
**File**: `taskiq/health/server.py`

Add worker-specific health check methods:

```python
def set_receiver(self, receiver: "Receiver | None") -> None:
    """Set receiver reference for worker health checks."""
    self._receiver = receiver

async def _check_readiness_worker(self) -> dict:
    """Check worker readiness."""
    checks = {
        "broker_connected": await self._check_broker_connectivity(),
        "receiver_initialized": self._check_receiver_initialized(),
        "prefetch_queue_healthy": self._check_prefetch_queue_health(),
    }

    all_passed = all(checks.values())
    return {
        "status": "ready" if all_passed else "not_ready",
        "type": "worker",
        "checks": checks
    }

async def _get_detailed_health_worker(self) -> dict:
    """Get detailed worker health."""
    return {
        "status": "healthy" if await self._is_healthy() else "unhealthy",
        "type": "worker",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "uptime_seconds": self._get_uptime(),
        "process": self._get_worker_process_info(),
        "broker": await self._get_broker_info(),
        "result_backend": await self._get_result_backend_info(),
        "checks": {
            "broker_connected": await self._check_broker_connectivity_with_detail(),
            "receiver_initialized": self._check_receiver_initialized(),
            "prefetch_queue_healthy": self._check_prefetch_queue_health(),
            "result_backend_healthy": await self._check_result_backend_health(),
        }
    }
```

### Phase 3: Scheduler Integration

#### Step 3.1: Add CLI Arguments to SchedulerArgs
**File**: `taskiq/cli/scheduler/args.py`

Add healthcheck configuration fields (same as worker but default port 8001).

#### Step 3.2: Add Middleware to Scheduler Startup
**File**: `taskiq/cli/scheduler/run.py`

Modify `run_scheduler()` function:

```python
async def run_scheduler(args: SchedulerArgs) -> None:
    # ... existing code ...

    # Add healthcheck middleware if enabled
    if args.healthcheck_enabled:
        health_middleware = HealthcheckMiddleware(
            enabled=True,
            port=args.healthcheck_port,
            host=args.healthcheck_host,
            # ... other args
        )
        scheduler.broker.add_middlewares(health_middleware)

    # ... rest of existing code ...
```

#### Step 3.3: Implement Scheduler Health Checks
**File**: `taskiq/health/server.py`

Add scheduler-specific health check methods similar to worker but with scheduler-specific logic.

### Phase 4: Testing

#### Step 4.1: Unit Tests
**File**: `tests/health/test_server.py`

Test HTTP server functionality:
- Server start/stop
- Endpoint responses
- Error handling
- Background task execution

#### Step 4.2: Integration Tests
**File**: `tests/health/test_worker_integration.py`

Test worker healthchecks:
- Worker startup with healthcheck enabled
- `/health` endpoint returns liveness
- `/ready` endpoint reflects worker state
- `/health/detailed` provides worker stats
- Healthcheck server doesn't block worker execution

#### Step 4.3: Integration Tests for Scheduler
**File**: `tests/health/test_scheduler_integration.py`

Test scheduler healthchecks:
- Scheduler startup with healthcheck enabled
- Endpoints reflect scheduler state
- Schedule sources health monitoring
- Next run times calculation

### Phase 5: Documentation

#### Step 5.1: Add Healthcheck Guide
**File**: `docs/guide/healthchecks.md`

Document:
- How to enable healthchecks
- Configuration options
- Endpoint specifications
- Integration with Kubernetes
- Custom health checks

#### Step 5.2: Update Worker Documentation
**File**: `docs/workers.md`

Add healthcheck section with examples.

#### Step 5.3: Update Scheduler Documentation
**File**: `docs/scheduler.md`

Add healthcheck section with examples.

---

## Testing Strategy

### Unit Tests

#### Healthcheck Server Tests
```python
@pytest.mark.asyncio
async def test_server_start_stop():
    """Test server can start and stop."""
    server = HealthcheckServer(port=18000)
    await server.start()
    assert server._site is not None
    await server.stop()
    assert server._site is None

@pytest.mark.asyncio
async def test_health_endpoint(aiohttp_client):
    """Test /health endpoint."""
    server = HealthcheckServer(port=18001)
    await server.start()

    resp = await aiohttp_client.get("http://localhost:18001/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "alive"

    await server.stop()

@pytest.mark.asyncio
async def test_ready_endpoint_worker(aiohttp_client):
    """Test /ready endpoint for worker."""
    server = HealthcheckServer(port=18002)
    await server.start()

    resp = await aiohttp_client.get("http://localhost:18002/ready")
    assert resp.status == 200
    data = await resp.json()
    assert "checks" in data
    assert "broker_connected" in data["checks"]

    await server.stop()
```

#### Middleware Tests
```python
@pytest.mark.asyncio
async def test_middleware_enabled():
    """Test middleware starts server when enabled."""
    broker = InMemoryBroker()
    broker.is_worker_process = True

    middleware = HealthcheckMiddleware(enabled=True, port=18000)
    middleware.set_broker(broker)

    await middleware.startup()
    # Verify server started
    await middleware.shutdown()

@pytest.mark.asyncio
async def test_middleware_disabled():
    """Test middleware doesn't start server when disabled."""
    broker = InMemoryBroker()
    middleware = HealthcheckMiddleware(enabled=False)

    middleware.set_broker(broker)
    await middleware.startup()
    # Verify server not started
    await middleware.shutdown()
```

### Integration Tests

#### Worker Integration Tests
```python
@pytest.mark.asyncio
async def test_worker_with_healthcheck():
    """Test worker starts and responds to healthchecks."""
    broker = InMemoryBroker()

    @broker.task
    async def test_task() -> None:
        pass

    # Start worker with healthcheck enabled
    worker_args = WorkerArgs(
        broker="module:broker",
        modules=["module"],
        healthcheck_enabled=True,
        healthcheck_port=18000,
    )

    # ... start worker process ...

    # Test health endpoints
    async with aiohttp.ClientSession() as session:
        resp = await session.get("http://localhost:18000/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["type"] == "worker"
```

#### Scheduler Integration Tests
```python
@pytest.mark.asyncio
async def test_scheduler_with_healthcheck():
    """Test scheduler starts and responds to healthchecks."""
    # Similar to worker test but for scheduler
```

### Performance Tests

- Verify healthcheck response time < 100ms
- Verify memory overhead < 5MB
- Verify no blocking on main event loop

---

## Security Considerations

### Host Binding

- Default: `0.0.0.0` (all interfaces)
- Production: Should bind to specific interface or use container networking
- Warning: Document security implications of binding to all interfaces

### Access Control

**Initial Implementation**: No authentication (same as Prometheus metrics)
**Future Enhancement**: API token support for protected endpoints

### Information Disclosure

**Liveness endpoint**: Minimal information (process alive)
**Readiness endpoint**: Check results only (no sensitive data)
**Detailed endpoint**: More information (configuration, not secrets)

---

## Future Enhancements

### Phase 2 Features

1. **Custom Health Checks**
   - Allow users to register custom health check functions via dependency injection
   - Support for application-specific health indicators

2. **Metrics Integration**
   - Expose healthcheck metrics to Prometheus middleware
   - Track healthcheck response times

3. **API Token Support**
   - Optional API token for protected healthcheck endpoints
   - Environment variable: `TASKIQ_HEALTHCHECK_TOKEN`

4. **Graceful Degradation**
   - Return degraded status when partially functional
   - Support for partial system failures

5. **Multiple Endpoints**
   - Support for multiple health check paths
   - Configurable per-environment (dev, staging, prod)

### Phase 3 Features

1. **Health Check History**
   - Track health status over time
   - Expose `/health/history` endpoint

2. **Alert Thresholds**
   - Configurable alerting thresholds
   - Integration with external alerting systems

3. **WebSocket Support**
   - Real-time health updates via WebSocket
   - For dashboard integration

---

## Migration Guide

### For Existing Users

No changes required - healthchecks are **opt-in by default**.

### For New Users

#### Worker Setup
```bash
# Start worker with healthchecks (auto-selects port)
taskiq worker path.to.module:broker \
  --healthcheck-enabled

# Start with explicit port
taskiq worker path.to.module:broker \
  --healthcheck-enabled \
  --healthcheck-port 17500

# Use environment variables
export TASKIQ_HEALTHCHECK_ENABLED=true
# Port auto-selection (recommended)
taskiq worker path.to.module:broker

# Explicit port
export TASKIQ_HEALTHCHECK_PORT=17600
taskiq worker path.to.module:broker
```

#### Scheduler Setup
```bash
# Start scheduler with healthchecks (auto-selects port)
taskiq scheduler path.to.module:scheduler \
  --healthcheck-enabled

# Start with explicit port
taskiq scheduler path.to.module:scheduler \
  --healthcheck-enabled \
  --healthcheck-port 17550
```

#### Kubernetes Deployment

```yaml
apiVersion: v1
kind: Deployment
metadata:
  name: taskiq-worker
spec:
  containers:
  - name: worker
    image: taskiq:latest
    args:
      - "path.to.module:broker"
      - "--healthcheck-enabled"
      # Port auto-selection - no need to specify port!
      # TaskIQ will find an available port in 17400-17499
    livenessProbe:
      httpGet:
        path: /health
        # Must match auto-selected port range
        # Or use named port (see alternative below)
        port: healthcheck
      initialDelaySeconds: 10
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /ready
        port: healthcheck
      initialDelaySeconds: 5
      periodSeconds: 5
```

**Alternative: Named Port** (for custom port specification):
```yaml
apiVersion: v1
kind: Deployment
metadata:
  name: taskiq-worker
spec:
  containers:
  - name: worker
    image: taskiq:latest
    args:
      - "path.to.module:broker"
      - "--healthcheck-enabled"
      - "--healthcheck-port=17500"  # Explicit port
    ports:
      - containerPort: 17500
        name: healthcheck
        protocol: TCP
    livenessProbe:
      httpGet:
        path: /health
        port: healthcheck  # References named port
      initialDelaySeconds: 10
      periodSeconds: 10
```

---

## Success Criteria

Implementation is considered complete when:

- [ ] Healthcheck middleware implements all 3 endpoints (`/health`, `/ready`, `/health/detailed`)
- [ ] Worker-specific health checks implemented (broker, receiver, prefetch queue)
- [ ] Scheduler-specific health checks implemented (broker, schedule sources, next runs)
- [ ] CLI arguments added for worker and scheduler (enabled, port, paths)
- [ ] Healthcheck server runs in background task without blocking
- [ ] Healthchecks disabled by default (opt-in)
- [ ] Unit tests cover HTTP server and middleware
- [ ] Integration tests for worker and scheduler
- [ ] Documentation updated with usage examples
- [ ] Kubernetes deployment guide provided
- [ ] All existing tests pass without changes
- [ ] Code follows taskiq conventions (middleware pattern, lifecycle hooks)

---

## Open Questions

1. **Broker Connection Check**: Should we add an abstract `check_connection()` method to `AsyncBroker` ABC? This would allow broker-specific implementations to provide their own connection health logic.

2. **Scheduler Type Detection**: How to distinguish scheduler mode? Options:
   - Add `is_scheduler_process` flag to broker (similar to `is_worker_process`)
   - Pass type to healthcheck middleware explicitly
   - Detect from running tasks/imports

3. **Port Conflicts**: Should we implement automatic port selection if default port is occupied?

4. **Health Check Timeout**: What timeout should be used for health checks? (Suggested: 5 seconds)

---

## References

- [Kubernetes Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [aiohttp Documentation](https://docs.aiohttp.org/)
- [Prometheus Middleware Pattern](taskiq/middlewares/prometheus_middleware.py)
- [FastAPI Health Checks](https://fastapi.tiangolo.com/advanced/sub-applications/)
- [TaskIQ Middleware System](taskiq/abc/middleware.py)
