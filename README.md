# The `electrumsv-bsor` package

Tokenized have developed a serialisation format that encodes in Bitcoin script object
representation, or BSOR for short. This package uses the test files from
[Tokenized's project](https://github.com/tokenized/pkg/tree/p2p/bsor) in order to verify
that it can both convert a binary representation to a decoded object, and to convert that decoded
object back to the same binary representation.

This package loosely follows the standard `dump`/`dumps`/`load`/`loads` API that standard library
modules like [json](https://docs.python.org/3/library/json.html) and
[pickle](https://docs.python.org/3/library/pickle.html) provide, although there are some extra
requirements for this package due to the need to the way data structures are defined.

## The package API

* `electrumsv_bsor.dump(object, stream, structure_metadata)`
* `data: bytes = electrumsv_bsor.dump(object, structure_metadata)`
* `object = electrumsv_bsor.load(stream, definition, class_reference)`
* `object = electrumsv_bsor.loads(data, definition, class_reference)`

For now, the nuances of how to use this are best observed in the test files.

## Structure markup in Python

The `structure_metadata` is how the encoder and decoder works out how to encode or decode
different types of objects. For non-structures like `PublicKey` they generally already provide
encoding and decoding methods directly to and from the desired encoding data type. For structures
like `XTestSubStruct` these must meet the definition requirements and considered a special
serialisation `OBJECT` data type.

```python
    structure_metadata: dict[str, tuple[Any, Any, FieldType]] = {
        "PublicKey": (PublicKey.from_bytes, lambda instance: instance.to_bytes, FieldType.BYTES),
        "XTestSubStruct": (XTestSubStruct, None, FieldType.OBJECT),
    }
```

Structures define their own BSOR encoding format and this is done using the standard library
[dataclasses](https://docs.python.org/3/library/dataclasses.html) module.

```python
@dataclass
class XTestStructSimple:
    IntField: int = field(metadata={ "bsor_id": 1 })
    StringField: str = field(metadata={ "bsor_id": 2 })
    IntZeroField: int = field(metadata={ "bsor_id": 3 })
    SubStruct: XTestSubStruct = field(metadata={ "bsor_id": 4     })
    BinaryField: bytes = field(metadata={ "bsor_id": 5 })
    IntPointerField1: int | None = field(metadata={ "bsor_id": 6 })
    IntPointerField2: int | None = field(metadata={ "bsor_id": 7 })
    PublicKeyField: PublicKey = field(metadata={ "bsor_id": 8  })
    ArrayStringPtrField: list[str|None] = field(metadata={ "bsor_id": 25 })
```

Each defined field in the structure must have a field identifier (`bsor_id` in the data classes
`metadata`) that matches the same value in any other definitions of the same structure in other
projects. The type of the field is drawn from the Python typing annotations, for example, in the
case of the `IntField` field it is `int`.

Other supported metadata entries are:

* `bsor_length` is used for fixed lengths of fields, whether string, bytes, lists or other types.
* `bsor_type` can be provided for fields with `float` annotation, and may be either
  `FieldType.FLOAT` or `FieldType.DOUBLE`.

Go pointer equivalence is considered to represented by `Optional` Python values and are indicated
with use of the `| None` Python type annotation.

## Warning

Any use of this package is best preceded with test data that exercises the structures to be used
for all variations.

## Implementation notes

There are various things that need testing and further work and are not hit by the test files
borrowed from the Tokenized project:

* `bsor_type` values are not actually tested in the test data, and it is possible that decoding
  of `FieldType.DOUBLE` values does not work. Encoding does not check this metadata field yet.
* `bsor_length` likely has a lot of edge cases that are not covered and may not even be
  representable in the current structures (lists of fixed length strings for instance).

The Python [dataclasses](https://docs.python.org/3/library/dataclasses.html) standard module keeps
type names in string format, which means there is no way of matching the type names to the classes
being referred to. This is what the `structure_metadata` dictionary provides coverage of, both
structures and encoded data types can be declared by the given `dataclasses` type name in this
dictionary.
