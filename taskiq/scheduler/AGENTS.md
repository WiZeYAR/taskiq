# SCHEDULER - TIME-BASED TASK EXECUTION

**Complexity Score: 28** | Domain: Temporal Task Management

## OVERVIEW
Modular scheduling system with pluggable schedule sources. Coordinates between `ScheduleSource` providers and broker for time-based task execution.

## STRUCTURE
```
taskiq/scheduler/
├── scheduler.py         # Core orchestrator
├── scheduled_task/      # Task models and validation
│   ├── v1.py         # Legacy scheduled task model
│   ├── v2.py         # Current model (46 lines, depth 4)
│   └── validators.py  # Pydantic validation logic
└── run.py              # CLI execution (421 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Core scheduler | `scheduler.py` | Orchestrates between sources and broker |
| Schedule sources | `abc/schedule_source.py` | Implement `get_schedules()` interface |
| Task models | `scheduled_task/` | Pydantic-based task definitions |
| CLI execution | `run.py` | Cron/interval/time scheduling loop |

## CONVENTIONS

### Scheduler Architecture
```
ScheduleSource(s) → TaskiqScheduler → SchedulerLoop → AsyncKicker → Broker
```

### Schedule Source Contract
```python
class MyScheduleSource(ScheduleSource):
    async def get_schedules(self) -> list[ScheduledTask]:
        # Return tasks to execute
        pass

    async def add_schedule(self, schedule: ScheduledTask) -> None:
        # Add schedule dynamically
        pass

    async def delete_schedule(self, schedule_id: str) -> None:
        # Remove schedule dynamically
        pass
```

### Three Schedule Types
- **Cron**: Uses `pycron` library with timezone/offset support
- **Interval**: Minimum 1-second intervals (no fractional seconds)
- **Time**: One-time execution at specific datetime

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ NEVER run multiple scheduler instances simultaneously (causes task duplication)
- ❌ Don't use fractional seconds in interval scheduling (minimum 1 second)
- ❌ Don't forget timezone handling - times are timezone-aware

## KEY PATTERNS

### TaskiqScheduler
Orchestrator that:
- Polls schedule sources periodically (default: 1 minute)
- Manages task execution lifecycle
- Handles task cancellation and error scenarios
- Integrates with broker via `AsyncKicker`

### ScheduledTask Models
Pydantic-based validation:
- `v2.py`: Current model with full validation
- `v1.py`: Legacy model for backward compatibility
- `validators.py`: Common validation logic

### Scheduler Loop (`run.py`)
Runtime engine with:
- 1-second loop interval for precision
- Timezone conversion and UTC handling
- Schedule deduplication (prevents double execution)
- Microsecond sleep alignment for consistent intervals
- Configurable skip-first-run for cold starts

### Time-Based Execution
**Cron Scheduling:**
```python
# Uses pycron.is_now() for evaluation
is_cron_task_now(cron_value, now, offset, last_run)
```

**Interval Scheduling:**
```python
# Minimum 1-second intervals enforced
is_interval_task_now(interval_value, now, last_run)
```

**Time-Based Scheduling:**
```python
# One-time execution at specific datetime
is_time_task_now(time_value, now, last_run)
```

## COMPLEXITY HOTSPOTS

### `run.py` (421 lines)
Temporal logic with:
- Complex time comparison logic
- Timezone conversion and handling
- Schedule deduplication
- Multi-threaded schedule fetching
- Memory management for last-run tracking

### `scheduled_task/v2.py` (46 lines, depth 4)
Validation logic with:
- Pydantic model definitions
- Schedule type validation (cron/interval/time)
- Argument and kwargs validation

## NOTES

### Scheduler Usage
```bash
# Start scheduler
taskiq scheduler path.to.module:broker

# The scheduler will:
# 1. Poll schedule sources every minute
# 2. Execute tasks at scheduled times
# 3. Send tasks to broker via AsyncKicker
```

### Schedule Management
- **Dynamic addition**: `await source.add_schedule(ScheduledTask(...))`
- **Dynamic removal**: `await source.delete_schedule(schedule_id)`
- **Wrapper objects**: `CreatedSchedule` for management
- **Immediate execution**: `schedule.kiq()` bypasses schedule

### Error Handling
- **Task cancellation**: `ScheduledTaskCancelledError` allows sources to veto execution
- **Source isolation**: Failed schedule retrieval doesn't crash scheduler
- **Graceful degradation**: Returns empty schedule list on errors

### Performance
- **Memory management**: Automatic cleanup of stale schedule tracking
- **Concurrency**: Async schedule fetching with `asyncio.gather()`
- **Resource efficiency**: Configurable update intervals
