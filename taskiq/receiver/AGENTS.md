# RECEIVER - TASK EXECUTION ENGINE

**Complexity Score: 20** | Domain: Task Runtime

## OVERVIEW
Core task execution engine with 7-stage processing pipeline. Handles sync/async execution, dependency injection, middleware orchestration, and result storage.

## STRUCTURE
```
taskiq/receiver/
└── receiver.py    # 472 lines - Core execution pipeline
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Task execution | `receiver.py` | Main callback() method with 7-stage pipeline |
| Dependency injection | `receiver.py` | Integration with taskiq_dependencies |
| Middleware orchestration | `receiver.py` | pre/post_execute, post_save, on_error hooks |

## CONVENTIONS

### Execution Pipeline
```python
async def callback(self, message, raise_err=False):
    # Stage 1: Message parsing and validation
    # Stage 2: Task resolution from broker registry
    # Stage 3: Middleware pre_execute hooks
    # Stage 4: Dependency injection via DependencyGraph
    # Stage 5: Actual execution with sync/async handling
    # Stage 6: Middleware post_execute hooks
    # Stage 7: Result storage and post_save hooks
```

### Sync/Async Bridge
```python
if check_coroutine_func(target):
    target_future = target(*message.args, **kwargs)  # Async path
else:
    # Sync path with context preservation
    target_future = loop.run_in_executor(self.executor, ctx.run, func)
```

### Dependency Injection
```python
if dependency_graph:
    broker_ctx = self.broker.custom_dependency_context
    dep_ctx = dependency_graph.async_ctx(broker_ctx, self.broker.dependency_overrides)
    kwargs = await dep_ctx.resolve_kwargs()
```

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't directly call task functions - use `run_task()` method
- ❌ Don't skip middleware hooks - they're called automatically by pipeline
- ❌ Don't forget to propagate context - Context variables preserved across execution

## COMPLEXITY HOTSPOTS

### `callback()` Method (70+ lines)
Multi-stage orchestration with:
- 6+ levels of indentation
- 7 distinct processing stages
- Exception handling at each stage
- Context propagation
- Result storage

### `run_task()` Method (90+ lines)
Execution logic with:
- Sync/async function detection and routing
- Timeout handling
- Dependency resolution
- Context variable preservation
- Error handling and result wrapping

## KEY PATTERNS

### Context Preservation
Task execution maintains context across async boundaries:
- `ContextVar` for task context
- Broker context injection
- Dependency context propagation

### Middleware Integration
Each hook receives appropriate data:
- `pre_execute(message)`: Called before execution
- `post_execute(message, result)`: Called after completion
- `post_save(message, result)`: Called after result storage
- `on_error(message, result, exception)`: Called on exceptions

### Result Storage
```python
# Stage 7: Result storage
if self.broker.result_backend:
    await self.broker.result_backend.set_result(
        task_id=message.task_id,
        result=result,
    )
```

### Error Handling
- Errors wrapped in `TaskiqResult` objects
- `TaskiqError` exceptions indicate task failures
- Middleware can modify error behavior via `on_error` hook
- Supports raise_err parameter for exception propagation

## NOTES

### Execution Flow
1. **Message arrives**: From broker.listen() method
2. **Task resolution**: Find function from broker.task_registry
3. **Middleware pre_execute**: All pre_execute hooks in registration order
4. **Dependency injection**: Resolve dependencies via taskiq_dependencies
5. **Execution**: Run task (sync or async) with timeout
6. **Middleware post_execute**: All post_execute hooks in reverse order
7. **Result storage**: Save to result_backend if configured
8. **Middleware post_save**: All post_save hooks in reverse order

### Prefetch Queue
- Configurable prefetch size for efficiency
- Semaphores control concurrent execution
- Reduces broker communication overhead

### Process Isolation
- Each worker process has own Receiver instance
- No shared state between workers
- Broker handles inter-process coordination

### Testing
- Comprehensive tests in `tests/receiver/test_receiver.py` (546 lines)
- Tests cover sync/async execution, context preservation, middleware integration
- Uses `AsyncQueueBroker` for deterministic testing

### Performance
- Semaphore-based concurrency control
- Async execution throughout
- Minimal blocking operations
- Efficient context propagation
