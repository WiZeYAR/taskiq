# MIDDLEWARES - TASK LIFECYCLE HOOKS

**Complexity Score: 18** | Domain: Cross-cutting Concerns

## OVERVIEW
Plugin system for intercepting task lifecycle events. All middlewares implement 7-hook `TaskiqMiddleware` interface defined in `taskiq/abc/middleware.py`.

## STRUCTURE
```
taskiq/middlewares/
├── simple_retry_middleware.py        # Error retry logic
├── smart_retry_middleware.py          # Exponential backoff retry
├── prometheus_middleware.py          # Metrics collection
├── opentelemetry_middleware.py        # OpenTelemetry tracing (315 lines)
└── taskiq_admin_middleware.py       # External API monitoring (180 lines)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add retry logic | `simple_retry_middleware.py` or `smart_retry_middleware.py` | Handle transient errors |
| Collect metrics | `prometheus_middleware.py` | Prometheus-compatible metrics |
| Add tracing | `opentelemetry_middleware.py` | Distributed tracing with spans |
| Monitor tasks | `taskiq_admin_middleware.py` | HTTP API for task lifecycle |

## CONVENTIONS

### Middleware Pattern
```python
class MyMiddleware(TaskiqMiddleware):
    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        # Modify or validate before sending to broker
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        # After task completion
        pass
```

### 7 Lifecycle Hooks
- **pre_send(message)**: Before task sent to broker (client-side)
- **post_send(message)**: After task sent to broker (client-side)
- **pre_execute(message)**: Before task execution (worker-side)
- **post_execute(message, result)**: After task completes (worker-side)
- **post_save(message, result)**: After result stored (worker-side)
- **on_error(message, result, exception)**: On task exception (worker-side)
- **on_event(event, data)**: On broker lifecycle events (both sides)

### Broker Integration
```python
broker = InMemoryBroker()
broker.add_middlewares(MyMiddleware())
```

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't modify message.message (bytes) directly - modify structured fields instead
- ❌ Don't call middleware hooks manually - broker handles it
- ❌ Don't forget async/await - all hooks are async

## KEY PATTERNS

### Retry Middleware (`simple_retry_middleware.py`)
- Configurable retry count and timeout
- Linear backoff between attempts
- Retries on specific exception types
- Retries both pre_send and pre_execute hooks

### Smart Retry (`smart_retry_middleware.py`)
- Exponential backoff strategy
- Maximum retry duration cap
- Configurable base backoff time
- Retries on transient failures

### Prometheus Middleware (`prometheus_middleware.py`)
- Counters for task sent/received/failed/success
- Histograms for execution duration
- Exposed at `/metrics` endpoint
- Requires `prometheus_client` extra

### OpenTelemetry Middleware (`opentelemetry_middleware.py`)
- Distributed tracing with spans
- Automatic span propagation
- Traces task execution across processes
- Requires `opentelemetry` extra
- Entry point: `taskiq_instrumentor` for auto-instrumentation

### Admin Middleware (`taskiq_admin_middleware.py`)
- HTTP API for task monitoring
- Endpoints for task lifecycle (get, list, cancel)
- Integration with aiohttp server
- Requires external admin server dependency

## NOTES

### Middleware Execution Order
Hooks execute in order of registration:
- Client-side: pre_send (1..N) → send → post_send (N..1)
- Worker-side: pre_execute (1..N) → execute → post_execute (N..1) → save → post_save (N..1)

### Error Handling
- Middleware can raise exceptions to abort execution
- `on_error` hook receives exception information
- Middleware can modify error behavior

### Context Propagation
- TaskiqMessage includes labels for correlation
- OpenTelemetry spans carry context across processes
- Admin API uses labels for task identification

### Performance
- Middleware hooks add overhead - keep logic minimal
- Avoid blocking I/O in hooks
- Use async operations exclusively

### Testing
- Test fixtures in `tests/middlewares/conftest.py`
- Mock broker in `AsyncQueueBroker` for testing
- Integration tests with real brokers for end-to-end
