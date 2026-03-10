# BROKERS - MESSAGE TRANSPORT LAYER

**Complexity Score: 22** | Domain: Message Brokers

## OVERVIEW
Message broker implementations that transport tasks between clients and workers. All inherit from `AsyncBroker` abstract base class defined in `taskiq/abc/broker.py`.

## STRUCTURE
```
taskiq/brokers/
├── inmemory_broker.py    # Local execution (no network)
├── zmq_broker.py          # ZeroMQ PUB/SUB broker
└── shared_broker.py        # Task registry broker (delegation)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Local testing | `inmemory_broker.py` | Executes tasks immediately via `Receiver.callback()` |
| Distributed messaging | `zmq_broker.py` | PUB socket on client, SUB socket on workers |
| Task registration | `shared_broker.py` | Pure for task discovery, delegates to default broker |

## CONVENTIONS

### Broker Implementation Pattern
```python
class MyBroker(AsyncBroker):
    def __init__(self):
        super().__init__()  # Critical for base initialization

    async def kick(self, message: BrokerMessage) -> None:
        # Send message.message to transport
        pass

    async def listen(self) -> AsyncGenerator[bytes | AckableMessage, None]:
        # Yield incoming messages
        yield message_data
```

### Connection Management
- **InMemoryBroker**: Uses ThreadPoolExecutor for local execution
- **ZeroMQBroker**: Different socket types based on `is_worker_process` flag
- **SharedBroker**: No transport - purely for task registration

### Lifecycle
- Call `await super().startup()` in custom `startup()` methods
- Call `await super().shutdown()` in custom `shutdown()` methods
- Resources initialized in `startup()`, cleaned in `shutdown()`

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't call `listen()` on `InMemoryBroker` - raises RuntimeError
- ❌ Don't use `kick()` or `listen()` on `SharedBroker` - both raise exceptions
- ❌ Don't forget to check `is_worker_process` flag for socket type selection

## KEY PATTERNS

### InMemoryBroker Specialization
- Overrides `kick()` to execute immediately via `Receiver.callback()`
- Stores results in built-in result backend
- Used for testing and local development

### ZeroMQBroker Specialization
- Creates PUB socket when `is_worker_process=False` (client mode)
- Creates SUB socket when `is_worker_process=True` (worker mode)
- Supports acknowledgments via `AckableMessage`

### SharedBroker Specialization
- Uses `SharedDecoratedTask` that delegates to default broker
- Both `kick()` and `listen()` raise exceptions
- Purely for task registry and discovery

## NOTES

### Broker Selection
- **InMemoryBroker**: Testing, local development, fast iteration
- **ZeroMQBroker**: Distributed systems, needs external broker setup
- **SharedBroker**: When tasks are distributed across multiple modules

### Transport Agnostic
Core broker logic separated from transport implementation in `AsyncBroker` ABC
- Task registration and discovery inherited from base
- Middleware management inherited from base
- Event system inherited from base

### Extensions
External broker packages available:
- `taskiq-nats`: NATS JetStream broker
- `taskiq-redis`: Redis broker
- `taskiq-aio-pika`: RabbitMQ broker
- `taskiq-aio-kafka`: Kafka broker

All implement the same `AsyncBroker` contract.
