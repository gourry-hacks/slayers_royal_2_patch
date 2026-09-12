"""Established EVE repacker with explicit input and output locations."""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path
from .inventory import *

def encode_bcd(value: int) -> int:
    if not 0 <= value <= 99:
        raise ValueError(f"BCD value out of range: {value}")
    return ((value // 10) << 4) | (value % 10)


def encode_cdl_location(lba: int) -> int:
    absolute_frame = lba + 150
    minute, remainder = divmod(absolute_frame, 60 * 75)
    second, frame = divmod(remainder, 75)
    return int.from_bytes(
        bytes((encode_bcd(minute), encode_bcd(second), encode_bcd(frame), 0)),
        "little",
    )


def parse_replacements(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"replacement must be NAME=PATH: {value}")
        name, raw_path = value.split("=", 1)
        if not name or not raw_path:
            raise ValueError(f"replacement must be NAME=PATH: {value}")
        if name in result:
            raise ValueError(f"duplicate replacement for {name}")
        result[name] = Path(raw_path)
    return result


def repack(
    basyo: bytes,
    eve: bytes,
    replacements: dict[str, bytes],
    output_eve_lba: int = EVE_LBA,
    input_eve_lba: int = EVE_LBA,
) -> tuple[bytes, bytes, list[dict[str, object]]]:
    inventory = build_inventory(basyo, eve, input_eve_lba)
    resources = inventory["resources"]
    known_names = {str(resource["name"]) for resource in resources}
    missing = set(replacements) - known_names
    if missing:
        raise ValueError(f"unknown EVE resources: {', '.join(sorted(missing))}")

    output = bytearray()
    starts: list[int] = []
    sizes: list[int] = []
    changes: list[dict[str, object]] = []
    for resource in resources:
        name = str(resource["name"])
        source_start = int(resource["start_offset"])
        source_size = int(resource["declared_size"])
        source_payload = eve[source_start : source_start + source_size]
        payload = replacements.get(name, source_payload)
        starts.append(len(output))
        sizes.append(len(payload))
        output.extend(payload)

        if name in replacements:
            changes.append(
                {
                    "index": int(resource["index"]),
                    "name": name,
                    "old_size": source_size,
                    "new_size": len(payload),
                    "old_sha256": hashlib.sha256(source_payload).hexdigest(),
                    "new_sha256": hashlib.sha256(payload).hexdigest(),
                }
            )

        if int(resource["index"]) + 1 < RESOURCE_COUNT:
            original_padding = int(resource["alignment_padding"])
            if payload == source_payload:
                pad_start = source_start + source_size
                output.extend(eve[pad_start : pad_start + original_padding])
            else:
                output.extend(b"\x00" * (align4(len(output)) - len(output)))

    patched_basyo = bytearray(basyo)
    # Resource zero (EVE_HELP) has no preceding boundary record.  Its runtime
    # location is the two-word base descriptor immediately before the normal
    # resource table, so it must move with an appended/relocated EVE archive.
    struct.pack_into(
        "<I",
        patched_basyo,
        RESOURCE_BASE_LOCATION_OFFSET,
        encode_cdl_location(output_eve_lba),
    )
    struct.pack_into(
        "<I", patched_basyo, RESOURCE_BASE_INTRA_SECTOR_OFFSET, 0
    )
    for index in range(RESOURCE_COUNT - 1):
        next_start = starts[index + 1]
        lba = output_eve_lba + next_start // RAW_USER_SIZE
        intra_sector = next_start % RAW_USER_SIZE
        struct.pack_into(
            "<III",
            patched_basyo,
            BOUNDARY_TABLE_START + index * 12,
            sizes[index],
            encode_cdl_location(lba),
            intra_sector,
        )

    return bytes(output), bytes(patched_basyo), changes
