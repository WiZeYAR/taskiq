# TASKIQ - PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-08
**Commit:** 3770e73
**Branch:** master

## OVERVIEW
Async distributed task queue with full async support. Competitor to Celery/Dramatiq with modern Python patterns, enterprise observability, and plugin-based architecture.

## STRUCTURE
```
./
├── taskiq/           # Core framework (brokers, scheduler, receivers, middlewares)
├── tests/            # Mirrors taskiq/ structure
├── docs/              # VuePress documentation
└── .github/           # CI/CD workflows
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add broker implementation | `taskiq/brokers/` | Inherit `AsyncBroker`, implement `kick()` and `listen()` |
| Create middleware | `taskiq/middlewares/` | Inherit `TaskiqMiddleware`, implement 7 hook points |
| Schedule tasks | `taskiq/scheduler/` | Use `ScheduleSource`, `TaskiqScheduler`, `AsyncKicker` |
| Debug task execution | `taskiq/receiver/` | Core execution engine with dependency injection |
| CLI commands | `taskiq/cli/` | Entry points via `taskiq_cli` group in pyproject.toml |
| Add serializer/formatter | `taskiq/serializers/` or `taskiq/formatters/` | Inherit from ABCs in `taskiq/abc/` |
| Abstract interfaces | `taskiq/abc/` | All plugin contracts defined here |

## CONVENTIONS

### Build System (NON-STANDARD)
- Uses `uv_build` backend instead of setuptools/poetry
- No `requirements.txt` - uses `uv.lock` for dependency management
- Install: `uv sync --all-extras`

### Code Quality
- **Black**: 88 char line length
- **Ruff**: Comprehensive linting (E,F,W,C90,I,N,D,ANN,S,B,COM,etc.)
- **MyPy**: Strict mode enabled with permissive settings (allow_untyped_calls, allow_subclassing_any)
- **Pre-commit**: Required - runs black, ruff, mypy

### Entry Points
- **Meta-CLI**: Uses `entry_points().select(group="taskiq_cli")` for dynamic command discovery
- Commands: `taskiq worker`, `taskiq scheduler`
- Workers: `path.to.module:broker` format

### Testing
- **Structure**: Tests mirror taskiq/ directory exactly
- **Fixtures**: Global `reset_broker()` (autouse=True) cleans state between tests
- **Execution**: `pytest` with `-n auto` for parallel execution
- **Mocking**: Uses `AsyncQueueBroker` in `tests/utils.py` for deterministic async testing

### Anti-Patterns (PROJECT-SPECIFIC)
- ❌ Constructor params: Don't use `result_backend=` or `id_generator=` in broker constructors - use `.with_result_backend()` / `.with_id_generator()` instead
- ❌ Scheduler instances: Never run multiple scheduler instances simultaneously (causes task duplication)
- ❌ Broker startup: Always call `await broker.startup()` before using any broker
- ❌ Deprecated fields: `log` field in results is deprecated, will be removed

### Dependencies
- **FastAPI-like DI**: Uses `taskiq_dependencies.Depends` for dependency injection
- **Pydantic**: Core for data validation (supports v1.x and v2.x)
- **Async-first**: All operations are async, use `asyncio.run_in_executor()` for sync code

## CODE MAP

| Symbol | Type | Location | Role |
|---------|------|----------|-------|
| `AsyncBroker` | ABC | `taskiq/abc/broker.py` | Core broker contract (kick, listen, task registry) |
| `TaskiqMiddleware` | ABC | `taskiq/abc/middleware.py` | 7-hook middleware system for task lifecycle |
| `TaskiqScheduler` | Class | `taskiq/scheduler/scheduler.py` | Orchestrates scheduling with brokers |
| `ScheduleSource` | ABC | `taskiq/abc/schedule_source.py` | Pluggable schedule providers |
| `AsyncKicker` | Class | `taskiq/kicker.py` | Prepares/dispatches scheduled tasks to brokers |
| `Receiver` | Class | `taskiq/receiver/receiver.py` | Task execution engine with DI and middleware |

## COMMANDS

```bash
# Development setup
uv sync --all-extras
pre-commit install

# Testing
pytest -n auto              # Parallel execution
tox                        # Multi-version testing (3.10-3.14)

# Workers
taskiq worker path.to.module:broker --fs-discover --reload

# Scheduler
taskiq scheduler path.to.module:broker

# Linting
pre-commit run -a
ruff check .
mypy taskiq/
```

## NOTES

### Architecture
- **Broker-centric design**: All task execution flows through broker abstraction
- **Dual registries**: Global (all tasks) + Local (broker-specific) task registries
- **Middleware pipeline**: 7 hooks: pre_send, post_send, pre_execute, post_execute, post_save, on_error
- **Process isolation**: Worker processes are spawned and managed by `ProcessManager`

### Complexity Hotspots
- `taskiq/abc/broker.py` (535 lines): Core task registration and event system
- `taskiq/receiver/receiver.py` (472 lines): Task execution with 7-stage pipeline
- `taskiq/cli/worker/process_manager.py` (443 lines): Multi-process orchestration with health checks
- `taskiq/cli/scheduler/run.py` (421 lines): Cron/interval/time scheduling with timezone handling

### Integration Patterns
- **OpenTelemetry**: Built-in instrumentation via entry point `taskiq_instrumentor`
- **Health checks**: HTTP health check server in `taskiq/health/`
- **Prometheus**: Metrics middleware in `taskiq/middlewares/prometheus_middleware.py`
- **Admin API**: External task lifecycle monitoring via `TaskiqAdminMiddleware`

### Scheduler Types
- **Cron**: Uses `pycron` library with timezone/offset support
- **Interval**: Minimum 1-second intervals (no fractional seconds)
- **Time**: One-time execution at specific datetime (timezone-aware)

### Serialization
- **Exception safety**: Recursive traversal with cycle detection in `taskiq/serialization.py`
- **Pydantic support**: Automatic serialization for models, dataclasses, TypedDict
- **Multiple formats**: JSON, Pickle, ORJSON, MSGPack, CBOR

### CI/CD
- **Multi-OS**: Tests on Ubuntu, Windows, macOS
- **Matrix**: Python 3.10-3.14 × Pydantic versions × OS = 30+ combinations
- **Publishing**: Uses `uv publish` with GitHub OIDC authentication
- **Docs**: VuePress deployed to separate repo (taskiq-python.github.io)
