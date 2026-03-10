# CLI - COMMAND LINE INTERFACE

**Complexity Score: 26** | Domain: Worker & Scheduler Orchestration

## OVERVIEW
Multi-level CLI architecture with dynamic command discovery via entry points. Separates worker and scheduler concerns into independent command modules.

## STRUCTURE
```
taskiq/cli/
├── worker/            # Worker process management
│   ├── cmd.py       # WorkerCMD (entry point)
│   ├── run.py       # Core execution (250 lines)
│   ├── args.py      # Argument parsing (316 lines)
│   ├── process_manager.py  # Multi-process orchestration (443 lines)
│   └── async_task_runner.py  # Task execution loop
└── scheduler/          # Scheduler process management
    ├── cmd.py       # SchedulerCMD (entry point)
    ├── run.py       # Core execution (421 lines)
    └── args.py      # Argument parsing
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Worker entry point | `worker/cmd.py` | WorkerCMD class registered as entry point |
| Worker execution | `worker/run.py` | Process initialization and broker startup |
| Worker orchestration | `worker/process_manager.py` | Multi-process lifecycle with health checks |
| Scheduler entry point | `scheduler/cmd.py` | SchedulerCMD class registered as entry point |
| Scheduler execution | `scheduler/run.py` | Cron/interval/time scheduling loop |
| CLI arguments | `*/args.py` | Pydantic-based argument parsing |

## CONVENTIONS

### Entry Point System
```toml
[project.entry-points.taskiq_cli]
worker = "taskiq.cli.worker.cmd:WorkerCMD"
scheduler = "taskiq.cli.scheduler.cmd:SchedulerCMD"
```

Commands discovered dynamically via `entry_points().select(group="taskiq_cli")`

### Command Pattern
All commands inherit from `TaskiqCMD`:
```python
class WorkerCMD(TaskiqCMD):
    def exec(self, args: WorkerArgs) -> None:
        # Implementation
        pass
```

### Argument Parsing
Uses Pydantic models for type-safe argument parsing:
- `from_cli()` class method parses command-line args
- Automatic validation and type conversion
- Extensive use of `Field()` for descriptions and defaults

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't manually parse command-line args - use Pydantic models in `args.py`
- ❌ Don't skip argument validation - `from_cli()` validates automatically
- ❌ Don't modify `process_manager.py` directly - use WorkerCMD/exec() entry point

## KEY PATTERNS

### Process Management (`worker/process_manager.py`)
Complex orchestration with multiple subsystems:
- **Health checks**: HTTP health check server integration
- **Signal handling**: SIGTERM/SIGINT for graceful shutdown
- **File watching**: Hot reload support via watchdog
- **Worker spawning**: Multi-process worker pool with restart logic
- **Failure recovery**: Configurable restart limits

### Scheduler Loop (`scheduler/run.py`)
Time-based task execution:
- **Cron scheduling**: Uses `pycron` with timezone offsets
- **Interval scheduling**: Minimum 1-second intervals
- **Time scheduling**: One-time execution at specific datetime
- **Schedule polling**: Default 1-minute refresh interval
- **Task dispatch**: Via `AsyncKicker` to broker

### Worker Execution (`worker/run.py`)
Process lifecycle:
- Broker initialization and startup
- Task listening loop via `broker.listen()`
- Graceful shutdown handling
- Signal integration with process_manager

## COMPLEXITY HOTSPOTS

### `worker/process_manager.py` (443 lines)
Multi-process orchestration with:
- Process lifecycle management
- Health check integration
- Signal handling
- File watching coordination
- Error recovery and restart logic

### `scheduler/run.py` (421 lines)
Temporal logic with:
- Complex timezone handling
- Time comparison logic
- Schedule deduplication
- Multi-threaded schedule fetching
- Memory management

### `worker/args.py` (316 lines)
Argument parsing with:
- Extensive field definitions
- Validation logic
- Type conversion
- Default value handling

## NOTES

### CLI Usage
```bash
# Worker
taskiq worker path.to.module:broker --fs-discover --reload --max-async-tasks 4

# Scheduler
taskiq scheduler path.to.module:broker
```

### Worker Patterns
- Multi-process worker pool for parallel task execution
- Health check server for monitoring (port 8000 by default)
- Hot reload on file changes (if `--reload` flag)
- Prefetch queue for efficiency

### Scheduler Patterns
- Single process (never run multiple instances!)
- Periodic schedule source polling
- Timezone-aware execution
- Task deduplication to prevent double execution

### Integration
- Workers and schedulers both import broker from user module
- Full middleware support for both paths
- Result backend integration for both paths
