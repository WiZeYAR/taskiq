# TESTS - MIRRORED TEST STRUCTURE

**Complexity Score: 22** | Domain: Quality Assurance

## OVERVIEW
Comprehensive test suite that mirrors taskiq/ structure exactly. Uses pytest with async support, parallel execution, and extensive mocking strategies.

## STRUCTURE
```
tests/
├── conftest.py              # Global fixtures (reset_broker, mock_sleep)
├── utils.py                 # AsyncQueueBroker test utility
├── abc/                    # Abstract base class tests
├── api/                    # API endpoint tests
├── brokers/                # Broker implementation tests
├── cli/                    # Command-line interface tests
│   ├── scheduler/          # Scheduler CLI tests
│   └── worker/             # Worker CLI tests
├── depends/                # Dependency injection tests
├── formatters/             # Message formatter tests
├── middlewares/            # Middleware tests
│   └── admin_middleware/   # Admin middleware specific tests
├── opentelemetry/          # OpenTelemetry integration tests
├── receiver/               # Task receiver tests (546 lines)
├── scheduler/              # Scheduler tests
└── serializers/            # Serialization tests
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Global fixtures | `conftest.py` | reset_broker (autouse), mock_sleep, anyio_backend |
| Test utilities | `utils.py` | AsyncQueueBroker for deterministic async testing |
| Broker tests | `brokers/` | InMemoryBroker, ZeroMQBroker tests |
| Receiver tests | `receiver/test_receiver.py` | Comprehensive execution pipeline tests |
| Scheduler tests | `scheduler/` | Cron/interval/time scheduling tests |
| Middleware tests | `middlewares/` | All middleware implementations |

## CONVENTIONS

### Test Configuration
```toml
[tool.pytest.ini_options]
log_level = 'INFO'
anyio_mode = "auto"
```

### Global Fixtures (conftest.py)
```python
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"

@pytest.fixture(autouse=True)
def reset_broker():
    # Auto-reset broker state between tests
    AsyncBroker.global_task_registry = {}
    AsyncBroker.is_worker_process = False
    AsyncBroker.is_scheduler_process = False

@pytest.fixture
def mock_sleep():
    # Makes asyncio.sleep 10000x faster
    pass
```

### AsyncQueueBroker (tests/utils.py)
```python
class AsyncQueueBroker(AsyncBroker):
    """Broker for testing using asyncio.Queue"""
    # Stores tasks in queue for deterministic testing
    # Includes wait_tasks() method for synchronization
    # listen() yields AckableMessage for testing
```

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't run tests sequentially - use `-n auto` for parallel execution
- ❌ Don't forget reset_broker runs automatically (autouse=True)
- ❌ Don't use real brokers for unit tests - use AsyncQueueBroker

## KEY PATTERNS

### Test Organization
- Mirrors taskiq/ structure exactly
- Each module has corresponding test directory
- Integration tests use real brokers
- Unit tests use AsyncQueueBroker

### Async Testing Patterns
```python
async def test_something():
    broker = InMemoryBroker()

    @broker.task
    async def test_task() -> str:
        return "result"

    kicked = await test_task.kiq()
    result = await kicked.wait_result()
    assert result.return_value == "result"
```

### Mocking Strategy
- **AsyncMock**: For async components
- **unittest.mock**: For sync components
- **Mock objects**: Configured return values and side effects

### Parameterized Testing
- Extensive use of `@pytest.mark.parametrize`
- Test data using fixtures with multiple scenarios
- Freezegun for time-based testing

## COMPLEXITY HOTSPOTS

### `receiver/test_receiver.py` (546 lines)
Comprehensive coverage with:
- 25+ test methods
- Sync/async task execution tests
- Context variable preservation tests
- Middleware integration tests
- Error handling and timeout scenarios

### Specialized Conventions

#### Broker Reset Fixture
The `reset_broker` fixture is `autouse=True`:
- Runs automatically before every test
- Cleans up global state
- Crucial for avoiding test pollution

#### Admin Middleware Tests
Multi-format DTO testing:
- Dataclasses (frozen, with slots)
- Pydantic models
- TypedDict
- Nested structures

## NOTES

### Test Execution
```bash
# Standard testing
pytest

# Parallel execution
pytest -n auto

# Multi-version testing (via tox)
tox
```

### Coverage Configuration
```toml
[tool.coverage.run]
omit = [
    "taskiq/__main__.py",
    "taskiq/abc/cmd.py",
    "taskiq/cli/scheduler/args.py",
    "taskiq/cli/scheduler/cmd.py",
    "taskiq/cli/utils.py",
    "taskiq/cli/worker/args.py",
    "taskiq/cli/worker/async_task_runner.py",
    "taskiq/cli/worker/cmd.py",
]
```

### Specialized Test Areas
- **OpenTelemetry**: Uses `opentelemetry.test.test_base.TestBase`
- **Admin middleware**: Uses aiohttp TestServer for HTTP integration
- **CLI testing**: Mock-based testing for command parsing

### Test Utilities
- **AsyncQueueBroker**: Deterministic async testing
- **Test broker with await_inplace=True**: For span ordering in OpenTelemetry tests
- **Custom exceptions**: For error scenario testing
- **UUID-based test data**: For uniqueness

### File-Specific Conventions
```toml
[tool.ruff.lint.per-file-ignores]
"tests/*" = [
    "S101",   # Use of assert detected
    "S301",   # Use of pickle detected
    "D103",   # Missing docstring in public function
    "SLF001", # Private member accessed
    "S311",   # Standard pseudo-random generators
    "D101",   # Missing docstring in public class
    "D102",   # Missing docstring in public method
    "PLR2004",  # Magic value
]
```
