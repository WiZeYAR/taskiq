# ABSTRACT BASE CLASSES

**Complexity Score: 34** | Domain: Plugin Interfaces

## OVERVIEW
Core plugin architecture defining contracts for all extensibility points in taskiq. Every broker, middleware, serializer, formatter, and result backend must implement these interfaces.

## STRUCTURE
```
taskiq/abc/
├── broker.py          # 535 lines - Core broker contract
├── middleware.py       # 143 lines - 7-hook middleware system
├── schedule_source.py  # 79 lines - Schedule provider interface
├── serializer.py       # Abstract serialization contract
├── formatter.py        # Abstract message formatting contract
├── result_backend.py   # 79 lines - Result storage interface
└── cmd.py             # Abstract command base class
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Create broker | `broker.py` | Implement `AsyncBroker` with `kick()` and `listen()` |
| Add middleware | `middleware.py` | Implement 7 hook points for task lifecycle |
| Implement schedule source | `schedule_source.py` | Provide `get_schedules()` for scheduler |
| Create serializer | `serializer.py` | Implement `dumpb()` and `loadb()` methods |
| Add result backend | `result_backend.py` | Implement `set_result()` and `get_result()` |

## CONVENTIONS

### Broker Contract (`AsyncBroker`)
All brokers MUST implement:
- `async def kick(self, message: BrokerMessage) -> None` - Send tasks to messaging system
- `def listen(self) -> AsyncGenerator[bytes | AckableMessage, None]` - Receive tasks from messaging system

### Middleware Hooks (`TaskiqMiddleware`)
7 lifecycle hooks available:
- **Client-side**: `pre_send(message)`, `post_send(message)`
- **Worker-side**: `pre_execute(message)`, `post_execute(message, result)`, `post_save(message, result)`, `on_error(message, result, exception)`

### Task Registry
Dual registry system:
- `global_task_registry: ClassVar[dict]` - All discovered tasks across all brokers
- `local_task_registry: dict` - Broker-specific tasks (override global)

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't inherit from ABCs directly without implementing all abstract methods
- ❌ Don't call super().__init__() incorrectly - required for base initialization
- ❌ Don't modify global_task_registry directly - use `find_task()` methods

## KEY PATTERNS

### Lifecycle Management
All components support async lifecycle:
- `async def startup() -> None` - Initialize connections/resources
- `async def shutdown() -> None` - Cleanup connections/resources

### Event System
`AsyncBroker` provides event handling:
- `TaskiqEvents` enum: CLIENT_STARTUP, WORKER_STARTUP, CLIENT_SHUTDOWN, WORKER_SHUTDOWN
- `on_event(event_type, handler)` - Register event listeners

### Type Safety
Extensive use of generics and type hints:
- `AsyncBroker[MessageT]` - Generic message types
- Proper variance annotations for extensibility

## NOTES

### Complexity
- `broker.py` is most complex ABC with 20+ methods, task registration logic, event system, and middleware management
- High abstraction level makes this enterprise-grade but requires careful understanding

### Implementation Requirements
- All broker implementations inherit dual registries and event system
- Middleware hooks receive `TaskiqMessage` or `TaskiqResult` objects
- Schedule sources must support dynamic add/delete operations

### Testing
- Use `_TestBroker` in `tests/abc/test_broker.py` for unit testing
- Test utilities in `tests/utils.py` provide `AsyncQueueBroker` for async testing
