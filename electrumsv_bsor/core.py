"""
This is an implementation of the BSOR serialisation format.

BSOR serialises Go structures. Python does not have structures, fixed size lists, pointers or
differentiation between floats and doubles. For this implementation structures are simulated
using the `dataclasses` functionality.

- Pointers are indicated with a possible `None` value. A pointer to a string can be indicated
  using `str | None` typing declaration. A pointer to a list of integers can be indicated using
  `list[int] | None`. Similarly a list of pointers to substructures in this case `SubStructure`
  can be indicated with `list[SubStructure | None]`.
- Structure field typing is declared using Python typing where `IntField` field of type `int` is
  specified similar to `IntField: int = ...`.
- Structure fields identifiers are specfied using the `metadata` parameter to `dataclasses.field`,
  in the following manner `field(metadata={ "bsor_id": 8 })`.
- Fixed array size is specified using the `metadata` parameter to `dataclasses.field`, in the
  following manner `field(metadata={ "bsor_id": 9, "bsor_length": 2 })`, where the `bsor_length`
  declares the fixed array size.
"""

from __future__ import annotations
import dataclasses
import enum
from io import BytesIO
import logging
import os
import struct
from typing import Any, BinaryIO, Generator, NamedTuple, Protocol

from bitcoinx import item_to_int, Ops, push_int, push_item, Script


GENERATOR = Generator[tuple[int, bytes | None], None, None]


logger = logging.getLogger("bsor.common")
# logger.setLevel(logging.DEBUG)

logger_r = logging.getLogger("bsor.read")
# logger_r.setLevel(logging.DEBUG)

logger_w = logging.getLogger("bsor.write")
# logger_w.setLevel(logging.DEBUG)


# These are not BSOR type numbers but rather for our own internal usage.
class FieldType(enum.IntEnum):
    INTEGER     = 1
    FLOAT       = 2
    DOUBLE      = 3
    LIST        = 4
    STRING      = 5
    BYTES       = 6
    OBJECT      = 7


TYPE_DEFAULTS = {
    FieldType.STRING: "",
    FieldType.BYTES: b"",
    FieldType.INTEGER: 0,
}



class DefinitionProtocol(Protocol):
    def get_field(self, field_identifier: int) -> NamedFieldEntry:
        ...

    def get_fields(self) -> list[NamedFieldEntry]:
        ...

    def get_field_entries(self) -> list[FieldEntry]:
        ...

    def get_field_entry(self, field_identifier: int) -> FieldEntry:
        ...

    def get_field_value(self, field_identifier: int) -> Any:
        ...

    def get_list_constraint(self, field_identifier: int) \
            -> tuple[DefinitionProtocol, FieldEntry, int]:
        """
        Gets the field type of the array items.
        """
        ...

    def get_definition(self, field_identifier) -> DefinitionProtocol:
        """
        Get the definition for a field that happens to be an object/sub-structure.
        """
        ...


class FieldTypeMetadata(NamedTuple):
    field_type: FieldType
    is_class_reference: bool = False
    stores_pointers: bool = False


class FieldEntry(NamedTuple):
    identifier: int
    type_metadata: FieldTypeMetadata

NamedFieldEntry = tuple[str, FieldEntry]


def map_type_name_to_field_type(type_name: str, class_references: dict[str, Any],
        field: dataclasses.Field[Any] | None=None) -> FieldTypeMetadata:
    stores_pointers = False
    if type_name.endswith(" | None"):
        type_name = type_name[:-7]
        stores_pointers = True

    if type_name == 'int':
        return FieldTypeMetadata(FieldType.INTEGER, False, stores_pointers)
    elif type_name == 'float':
        if field is None:
            return FieldTypeMetadata(FieldType.FLOAT)
        field_type = field.metadata.get("bsor_type", FieldType.FLOAT)
        assert field_type in { FieldType.FLOAT, FieldType.DOUBLE }
        return FieldTypeMetadata(field_type, False, stores_pointers)
    elif type_name.startswith('list['):
        return FieldTypeMetadata(FieldType.LIST, False, stores_pointers)
    elif type_name == 'str':
        return FieldTypeMetadata(FieldType.STRING, False, stores_pointers)
    elif type_name == 'bytes':
        return FieldTypeMetadata(FieldType.BYTES, False, stores_pointers)
    if type_name in class_references:
        _decoder_callable, _encoder_callable, field_type = class_references[type_name]
        return FieldTypeMetadata(field_type, True, stores_pointers)
    raise Exception(f"Unknown type '{type_name}'")


class DataclassDefinition:
    def __init__(self, dataclass_object: Any, class_references: dict[str, Any]) -> None:
        self._dataclass_object = dataclass_object
        self._class_references = class_references

        encountered_identifiers = set[int]()
        fields: list[NamedFieldEntry] = []
        for dataclass_field in dataclasses.fields(self._dataclass_object):
            assert "bsor_id" in dataclass_field.metadata, dataclass_field
            field_id = dataclass_field.metadata["bsor_id"]
            encountered_identifiers.add(field_id)
            field_type_data = map_type_name_to_field_type(dataclass_field.type,
                self._class_references, dataclass_field)
            fields.append((dataclass_field.name, FieldEntry(field_id, field_type_data)))
        self._fields = fields

    def get_field(self, field_identifier: int) -> NamedFieldEntry:
        for named_field in self._fields:
            if named_field[1].identifier == field_identifier:
                return named_field
        raise ValueError(f"Field {field_identifier} not found")

    def get_fields(self) -> list[NamedFieldEntry]:
        return self._fields

    def get_field_entries(self) -> list[FieldEntry]:
        return [ field_entry for field_name, field_entry in self._fields ]

    def get_field_entry(self, field_identifier: int) -> FieldEntry:
        for field in self.get_field_entries():
            if field[0] == field_identifier:
                return field
        raise ValueError(f"Unexpected field identifier {field_identifier}")

    def get_field_value(self, field_identifier: int) -> tuple[Any, Any]:
        for entry_field_name, entry_field_entry in self._fields:
            if entry_field_entry.identifier == field_identifier:
                logger.debug("get_field_value %s, %s", entry_field_name, entry_field_entry)
                field = self._dataclass_object.__dataclass_fields__[entry_field_name]
                field_type_name = field.type
                if field_type_name in { "int", "float", "str", "bytes" }:
                    return getattr(self._dataclass_object, entry_field_name)

                stores_pointers = False
                if field_type_name.startswith("list["):
                    field_type_name = field.type[5:-1]
                if field_type_name.endswith(" | None"):
                    field_type_name = field_type_name[:-7]
                    stores_pointers = True
                return self._class_references[field_type_name][0], \
                    self._class_references[field_type_name][1]
        raise ValueError(f"Unexpected field identifier {field_identifier}")

    def get_list_constraint(self, field_identifier: int) \
            -> tuple[DefinitionProtocol, FieldEntry, int]:
        """
        Gets the field type of the array items.
        """
        for entry_field_name, entry_field_entry in self._fields:
            if entry_field_entry.identifier == field_identifier:
                field = self._dataclass_object.__dataclass_fields__[entry_field_name]
                item_count = field.metadata.get("bsor_length", None)
                field_type_name = field.type[5:-1]
                field_type_data = map_type_name_to_field_type(field_type_name,
                    self._class_references)
                logger.debug("get_list_constraint(%d) = %s", field_identifier, field_type_data)
                return self, FieldEntry(field_identifier, field_type_data), item_count
        raise ValueError(f"Unexpected field identifier {field_identifier}")

    def get_definition(self, field_identifier) -> DefinitionProtocol:
        """
        Get the definition for a field that happens to be an object/sub-structure.
        """
        class_reference, decoder_callable = self.get_field_value(field_identifier)
        assert decoder_callable is None
        logger.debug("get_definition for %s", class_reference)
        return self.__class__(class_reference, self._class_references)


def _read_structure(generator: GENERATOR, definition: DefinitionProtocol, class_reference: Any) \
        -> dict[str, Any]:
    opcode, value_bytes = next(generator)
    field_count = item_to_int(value_bytes)
    logger_r.debug("_read_structure.START: field_count=%d", field_count)
    kwargs: dict[str, Any] = {}
    for _field_index in range(field_count):
        field_id, field_value = _read_field(generator, definition)
        field_name, _field = definition.get_field(field_id)
        kwargs[field_name] = field_value
    for field_name, field in definition.get_fields():
        if field_name not in kwargs:
            if field.type_metadata.stores_pointers:
                kwargs[field_name] = None
                logger_r.debug("populating nil %s", field_name)
            elif field.type_metadata.field_type in TYPE_DEFAULTS:
                kwargs[field_name] = TYPE_DEFAULTS[field.type_metadata.field_type]
                logger_r.debug("populating default %s %s", field_name, kwargs[field_name])
    logger_r.debug("_read_structure.END")
    return class_reference(**kwargs)


def _read_field(generator: GENERATOR, definition: DefinitionProtocol) -> Any:
    opcode, value_bytes = next(generator)
    field_identifier = item_to_int(value_bytes)
    logger_r.debug("_read_field(%d)", field_identifier)
    field_entry = definition.get_field_entry(field_identifier)
    field_value = _read_type(generator, definition, field_entry)
    return field_identifier, field_value


def _read_type(generator: GENERATOR, definition: DefinitionProtocol,
        field_entry: FieldEntry) -> Any:
    if field_entry.type_metadata.is_class_reference and \
            field_entry.type_metadata.field_type != FieldType.OBJECT:
        decode_callable, _encode_callable = definition.get_field_value(field_entry.identifier)
        opcode, value_bytes = next(generator)
        field_value = decode_callable(value_bytes)
    elif field_entry.type_metadata.field_type == FieldType.INTEGER:
        opcode, value_bytes = next(generator)
        field_value = item_to_int(value_bytes)
    elif field_entry.type_metadata.field_type == FieldType.FLOAT:
        opcode, value_bytes = next(generator)
        if value_bytes is None or len(value_bytes) != 4:
            raise ValueError("Invalid float length, expected 4 bytes, "
                f"got {len(value_bytes) if value_bytes is not None else None}")
        field_value, = struct.unpack("<f", value_bytes)
    elif field_entry.type_metadata.field_type == FieldType.DOUBLE:
        opcode, value_bytes = next(generator)
        if value_bytes is None or len(value_bytes) != 8:
            raise ValueError(f"Invalid float length, expected 8 bytes, "
                f"got {len(value_bytes) if value_bytes is not None else None}")
        field_value, = struct.unpack("<d", value_bytes)
    elif field_entry.type_metadata.field_type == FieldType.BYTES:
        opcode, value_bytes = next(generator)
        field_value = value_bytes
    elif field_entry.type_metadata.field_type == FieldType.STRING:
        opcode, value_bytes = next(generator)
        if value_bytes is None:
            raise ValueError("Invalid string, expected pushdata got None")
        field_value = value_bytes.decode("utf-8")
    elif field_entry.type_metadata.field_type == FieldType.LIST:
        list_definition, item_field_entry, item_count \
            = definition.get_list_constraint(field_entry.identifier)
        if item_count is None:
            opcode, value_bytes = next(generator)
            item_count = item_to_int(value_bytes)
        # Python does not have pointers.
        logger_r.debug("list[%s], %d items", item_field_entry, item_count)
        field_value = []
        for _item_index in range(item_count):
            if item_field_entry.type_metadata.stores_pointers:
                opcode, value_bytes = next(generator)
                if opcode == Ops.OP_0:
                    field_value.append(None)
                    continue
                elif opcode != Ops.OP_1:
                    raise ValueError("List of pointers contains a non-zero/non-one entry prefix "+
                        f"{opcode}: {value_bytes}")
            field_value.append(_read_type(generator, list_definition, item_field_entry))
    elif field_entry.type_metadata.field_type == FieldType.OBJECT:
        next_definition = definition.get_definition(field_entry.identifier)
        class_reference, decoder_value = definition.get_field_value(field_entry.identifier)
        assert decoder_value is None
        field_value = _read_structure(generator, next_definition, class_reference)
    else:
        raise NotImplementedError(f"field_type {field_entry.type_metadata.field_type}")
    logger_r.debug("_read_type(%s) -> %r", field_entry, field_value)
    return field_value


def load(stream: BinaryIO, definition: DefinitionProtocol, class_reference: Any) -> Any:
    script_iterator = Script(stream.read()).ops_and_items()
    return _read_structure(script_iterator, definition, class_reference)


def loads(data: bytes, definition: DefinitionProtocol, class_reference: Any) -> Any:
    script_iterator = Script(data).ops_and_items()
    return _read_structure(script_iterator, definition, class_reference)



def _write_structure(stream: BinaryIO, definition: DefinitionProtocol, object_value: Any) -> None:
    # Filter out fields that
    fields = list[NamedFieldEntry]()
    for named_field in definition.get_fields():
        field_name, field_entry = named_field
        if not hasattr(object_value, field_name):
            continue
        field_value = getattr(object_value, field_name)
        if field_entry.type_metadata.field_type in TYPE_DEFAULTS:
            if field_entry.type_metadata.stores_pointers:
                if field_value is None:
                    logger_w.debug("Skip field for write %s (pointer)", field_name)
                    continue
            elif field_value == TYPE_DEFAULTS[field_entry.type_metadata.field_type]:
                logger_w.debug("Skip field for write %s", field_name)
                continue
        logger_w.debug("Write field %s", field_name)
        fields.append(named_field)

    stream.write(push_int(len(fields)))
    for field_name, (field_identifier, field_type_metadata) in fields:
        if hasattr(object_value, field_name):
            logger_w.debug("Found %s on %s", field_name, object_value.__class__)
            field_value = getattr(object_value, field_name)
            _write_field(stream, definition, field_identifier, field_type_metadata, field_value)


def _write_field(stream: BinaryIO, definition: DefinitionProtocol, field_identifier: int,
        field_type_metadata: FieldTypeMetadata, field_value: Any) -> None:
    stream.write(push_int(field_identifier))
    try:
        _write_type(stream, definition, field_identifier, field_type_metadata, field_value)
    except Exception:
        logger_w.debug("%s", field_type_metadata)
        raise


def _write_type(stream: BinaryIO, definition: DefinitionProtocol, field_identifier: int,
        field_type_metadata: FieldTypeMetadata, field_value: Any) -> None:
    if field_type_metadata.is_class_reference and \
            field_type_metadata.field_type != FieldType.OBJECT:
        _decode_callable, encoder_callable_factory = definition.get_field_value(field_identifier)
        if field_type_metadata.field_type == FieldType.BYTES:
            field_value = encoder_callable_factory(field_value)()
        else:
            raise NotImplementedError("Needs encoder for class instance field, with type "+
                str(field_type_metadata.field_type))

    if field_type_metadata.field_type == FieldType.INTEGER:
        stream.write(push_int(field_value))
    elif field_type_metadata.field_type == FieldType.FLOAT:
        float_value = struct.pack("<f", field_value)
        stream.write(push_item(float_value))
    elif field_type_metadata.field_type == FieldType.DOUBLE:
        double_value = struct.pack("<d", field_value)
        stream.write(push_item(double_value))
    elif field_type_metadata.field_type == FieldType.BYTES:
        stream.write(push_item(field_value))
    elif field_type_metadata.field_type == FieldType.STRING:
        stream.write(push_item(field_value.encode()))
    elif field_type_metadata.field_type == FieldType.LIST:
        list_definition, item_field_entry, item_count \
            = definition.get_list_constraint(field_identifier)
        if item_count is None:
            item_count = len(field_value)
            stream.write(push_int(item_count))
        for _item_index, item_value in enumerate(field_value):
            if item_field_entry.type_metadata.stores_pointers:
                # Lists of pointers have a 0 for a nil, or a 1 followed by the value pointed to.
                if item_value is None:
                    stream.write(push_int(0))
                    continue
                stream.write(push_int(1))
            _write_type(stream, list_definition, field_identifier,
                item_field_entry.type_metadata, item_value)
    elif field_type_metadata.field_type == FieldType.OBJECT:
        next_definition = definition.get_definition(field_identifier)
        _write_structure(stream, next_definition, field_value)
    else:
        raise NotImplementedError("")
    return field_value



def dump(object: Any, stream: BinaryIO, structure_metadata: dict[str, Any]) -> None:
    definition = DataclassDefinition(object.__class__, structure_metadata)
    _write_structure(stream, definition, object)


def dumps(object: Any, structure_metadata: dict[str, Any]) -> bytes:
    stream = BytesIO()
    dump(object, stream, structure_metadata)
    stream.seek(0, os.SEEK_SET)
    return stream.read()
