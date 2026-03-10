# SERIALIZERS - DATA SERIALIZATION LAYER

**Complexity Score: 12** | Domain: Data Serialization

## OVERVIEW
Pluggable serialization system for converting Python objects to/from bytes. Supports multiple formats with Pydantic/dataclass compatibility.

## STRUCTURE
```
taskiq/serializers/
├── __init__.py              # Public API exports
├── json_serializer.py         # JSON format (built-in)
├── pickle_serializer.py        # Pickle format (built-in)
├── orjson_serializer.py        # ORJSON format (extra: orjson)
├── msgpack_serializer.py       # MessagePack format (extra: msgpack)
└── cbor_serializer.py         # CBOR format (extra: cbor2)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| JSON serialization | `json_serializer.py` | Default, built-in serializer |
| Pickle serialization | `pickle_serializer.py` | Fast, Python-specific |
| ORJSON serialization | `orjson_serializer.py` | Fast JSON alternative (extra: orjson) |
| MessagePack serialization | `msgpack_serializer.py` | Binary format (extra: msgpack) |
| CBOR serialization | `cbor_serializer.py` | Compact binary (extra: cbor2) |

## CONVENTIONS

### Serializer Contract (`TaskiqSerializer`)
All serializers MUST implement:
```python
class TaskiqSerializer(ABC):
    @abstractmethod
    def dumpb(self, value: Any) -> bytes:
        # Serialize to bytes
        pass

    @abstractmethod
    def loadb(self, data: bytes) -> Any:
        # Deserialize from bytes
        pass
```

### Pydantic/Dataclass Support
Serializers automatically handle:
- Pydantic models (v1.x and v2.x)
- Dataclasses
- TypedDict
- Standard Python types

### Exception Safety
- Recursive traversal with cycle detection
- Security validation against code injection
- Custom exception chain reconstruction

## ANTI-PATTERNS (THIS PACKAGE)

- ❌ Don't use pickle for untrusted data - security risk
- ❌ Don't forget exception handling - serialization can fail
- ❌ Don't mix serializer types - all tasks use broker serializer

## KEY PATTERNS

### Format Selection
```python
# Use extra dependencies for faster/more efficient formats
broker = InMemoryBroker().with_serializer(ORJSONSerializer())
broker = InMemoryBroker().with_serializer(MSGPackSerializer())
```

### Built-in vs Extras
- **Built-in**: JSON (default), Pickle (fast, Python-specific)
- **Extras**: ORJSON (fast), MessagePack (compact), CBOR (efficient)

### Broker Integration
```python
# Via builder pattern
broker = InMemoryBroker().with_serializer(JSONSerializer())

# Or via parameter (legacy, not recommended)
broker = InMemoryBroker(serializer=JSONSerializer())  # ❌ Deprecated
```

## NOTES

### Serialization Usage
- Broker uses serializer to convert `BrokerMessage` to bytes for transport
- Receiver deserializes bytes to `BrokerMessage` for processing
- Format choice affects: speed, size, cross-language compatibility

### Performance Characteristics
- **JSON**: Standard, human-readable, moderate speed/size
- **Pickle**: Fast, Python-specific, smaller size
- **ORJSON**: Very fast, JSON-compatible
- **MessagePack**: Compact, binary, fast
- **CBOR**: Very compact, binary, standard

### Security Considerations
- Pickle can execute arbitrary code - only for trusted data
- JSON/ORJSON safer for untrusted sources
- All serializers validate input types before serialization
