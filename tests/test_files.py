from __future__ import annotations
from dataclasses import dataclass, field
from io import BytesIO
import logging
import pathlib
from typing import Any

from bitcoinx import PublicKey
import pytest

import electrumsv_bsor
from electrumsv_bsor import FieldType

logger = logging.getLogger("bsor-test")
# logger.setLevel(logging.DEBUG)


@dataclass
class XTestSubStruct:
    SubIntField: int = field(metadata={ "bsor_id": 1 })
    SubStringField: str = field(metadata={ "bsor_id": 2 })


@dataclass
class XTestStruct:
    IntField: int = field(metadata={ "bsor_id": 1 })
    StringField: str = field(metadata={ "bsor_id": 2 })
    SubStruct: XTestSubStruct = field(metadata={ "bsor_id": 3 })
    SubStructPtr: XTestSubStruct = field(metadata={ "bsor_id": 4 })
    BinaryField: bytes = field(metadata={ "bsor_id": 5 })
    FixedBinaryField:  bytes = field(metadata={ "bsor_id": 6, "bsor_length": 4 })
    PointerField: str|None = field(metadata={ "bsor_id": 7 })
    ArrayPrimitiveField: list[str] = field(metadata={ "bsor_id": 8 })
    FixedArrayPrimitiveField: list[int] = field(metadata={ "bsor_id": 9, "bsor_length": 2 })
    ArrayObjectField: list[XTestSubStruct] = field(metadata={ "bsor_id": 10 })
    FixedArrayObjectField: list[XTestSubStruct] = field(metadata={ "bsor_id": 11, "bsor_length": 2 })
    ArrayObjectPtrField: list[XTestSubStruct|None] = field(metadata={ "bsor_id": 12 })
    ArrayStringPtrField: list[str|None] = field(metadata={ "bsor_id": 13 })
    PublicKeyField: PublicKey = field(metadata={ "bsor_id": 14  })
    PublicKeyPtrField: PublicKey|None = field(metadata={ "bsor_id": 15 })
    PublicKeyPtrField2: PublicKey|None = field(metadata={ "bsor_id": 16 })
    PublicKeyArrayField: list[PublicKey] = field(metadata={ "bsor_id": 17 })
    PublicKeyFixedArrayField: list[PublicKey] = field(metadata={ "bsor_id": 18, "bsor_length": 2 })
    PublicKeyPtrArrayField: list[PublicKey|None] = field(metadata={ "bsor_id": 19 })
    PublicKeyPtrFixedArrayField: list[PublicKey|None] = field(metadata={ "bsor_id": 20, "bsor_length": 2 })
    IntPtrField: int|None = field(metadata={ "bsor_id": 21 })
    IntPtrNilField: int|None = field(metadata={ "bsor_id": 22 })
    IntPtrZeroField: int|None = field(metadata={ "bsor_id": 23  })
    FixedStringField: str = field(metadata={ "bsor_id": 24, "bsor_length": 5 })


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


def get_test_file_paths() -> list[pathlib.Path]:
    test_path = pathlib.Path(__file__).parent.resolve()
    test_file_path = test_path / "test_files"
    assert test_file_path.exists()

    matches: list[pathlib.Path] = []
    for file_path in test_file_path.iterdir():
        if file_path.suffix == ".bsor":
            matches.append(file_path)
    return matches



@pytest.mark.parametrize("file_path", get_test_file_paths())
def test_file(file_path: pathlib.Path) -> None:
    structure_metadata: dict[str, tuple[Any, Any, FieldType]] = {
        "PublicKey": (PublicKey.from_bytes, lambda instance: instance.to_bytes, FieldType.BYTES),
        "XTestSubStruct": (XTestSubStruct, None, FieldType.OBJECT),
    }

    file_definitions = {
        "object_1": electrumsv_bsor.DataclassDefinition(XTestStructSimple, structure_metadata),
        "object_2": electrumsv_bsor.DataclassDefinition(XTestStruct, structure_metadata),
    }

    # json_path = file_path.with_suffix(".json")

    with open(file_path, "rb") as bsor_file:
        logger.debug("Reading '%s'", file_path)
        file_structure = electrumsv_bsor.load(bsor_file, file_definitions[file_path.stem],
			file_definitions[file_path.stem]._dataclass_object)
        print(file_structure)

        import os
        bsor_file.seek(0, os.SEEK_SET)
        original_data =bsor_file.read()
        logger.debug("OLD %d %s", len(original_data), original_data.hex())

        stream = BytesIO()
        try:
            electrumsv_bsor.dump(file_structure, stream, structure_metadata)
        except Exception:
            stream.seek(0, os.SEEK_SET)
            current_data = stream.read()
            logger.debug("CUR %d %s", len(current_data), current_data.hex())
            raise
        stream.seek(0, os.SEEK_SET)
        stream.read()
        reencoded_data = electrumsv_bsor.dumps(file_structure, structure_metadata)
        logger.debug("NEW %d %s", len(reencoded_data), reencoded_data.hex())
        if not original_data.startswith(reencoded_data):
            for i in range(len(original_data)):
                if reencoded_data[i] != original_data[i]:
                    logger.debug("MISMATCH %d", i)
                    break
