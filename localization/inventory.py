#!/usr/bin/env python3
"""Inventory Royal 2 logical resources packed into EVE_DATA.ST2.

BASYO.BIN retains the 688 resource names in reverse order and a companion
table of 687 on-disc boundary descriptors.  The descriptors encode the prior
resource size, a BCD CD location, and the next resource's logical byte offset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


BASYO_SHA256 = "c11cb06e12f27e8f73f1e9b7106a15fbe0049417e4c73dd18553b979da32dc00"
EVE_SHA256 = "c3f4a97b0412aadbb4ff948b5aca7322408fc59e594309ea5e88fbeb0360ed3e"
EVE_LBA = 124475
NAME_POOL_START = 0xF4
NAME_POOL_END = 0x2B98
BOUNDARY_TABLE_START = 0x333F0
RESOURCE_BASE_LOCATION_OFFSET = BOUNDARY_TABLE_START - 8
RESOURCE_BASE_INTRA_SECTOR_OFFSET = BOUNDARY_TABLE_START - 4
RESOURCE_COUNT = 688
RAW_USER_SIZE = 2048


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align4(value: int) -> int:
    return (value + 3) & ~3


def decode_bcd(value: int) -> int:
    high = value >> 4
    low = value & 0x0F
    if high > 9 or low > 9:
        raise ValueError(f"invalid BCD byte 0x{value:02X}")
    return high * 10 + low


def decode_cdl_location(value: int) -> tuple[int, str]:
    raw = value.to_bytes(4, "little")
    minute, second, frame = (decode_bcd(byte) for byte in raw[:3])
    if second >= 60 or frame >= 75 or raw[3] != 0:
        raise ValueError(f"invalid CD location {raw.hex()}")
    lba = (minute * 60 + second) * 75 + frame - 150
    return lba, f"{minute:02d}:{second:02d}:{frame:02d}"


def parse_names(basyo: bytes) -> list[dict[str, object]]:
    pool = basyo[NAME_POOL_START:NAME_POOL_END]
    source_order = [
        {
            "pool_offset": NAME_POOL_START + match.start(),
            "name": match.group().decode("ascii"),
        }
        for match in re.finditer(rb"[ -~]{4,}", pool)
    ]
    if len(source_order) != RESOURCE_COUNT:
        raise ValueError(
            f"expected {RESOURCE_COUNT} resource names, found {len(source_order)}"
        )
    return list(reversed(source_order))


def parse_boundaries(
    basyo: bytes,
    eve_lba: int = EVE_LBA,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index in range(RESOURCE_COUNT - 1):
        offset = BOUNDARY_TABLE_START + index * 12
        delta, location, intra_sector = struct.unpack_from("<III", basyo, offset)
        lba, msf = decode_cdl_location(location)
        file_offset = (lba - eve_lba) * RAW_USER_SIZE + intra_sector
        result.append(
            {
                "index": index,
                "table_offset": offset,
                "delta": delta,
                "cd_location": location,
                "msf": msf,
                "lba": lba,
                "intra_sector": intra_sector,
                "file_offset": file_offset,
            }
        )
    return result


def build_inventory(
    basyo: bytes,
    eve: bytes,
    eve_lba: int = EVE_LBA,
) -> dict[str, object]:
    base_location = struct.unpack_from(
        "<I", basyo, RESOURCE_BASE_LOCATION_OFFSET
    )[0]
    base_lba, base_msf = decode_cdl_location(base_location)
    base_intra_sector = struct.unpack_from(
        "<I", basyo, RESOURCE_BASE_INTRA_SECTOR_OFFSET
    )[0]
    if base_lba != eve_lba or base_intra_sector != 0:
        raise ValueError(
            "EVE resource base descriptor does not address the first byte of "
            f"the archive: LBA {base_lba}, intra {base_intra_sector}, "
            f"expected LBA {eve_lba}, intra 0"
        )

    names = parse_names(basyo)
    boundaries = parse_boundaries(basyo, eve_lba)
    starts = [0] + [int(boundary["file_offset"]) for boundary in boundaries]
    if starts != sorted(starts) or len(set(starts)) != RESOURCE_COUNT:
        raise ValueError("resource starts are not strictly increasing")
    if starts[-1] >= len(eve):
        raise ValueError("last resource starts beyond EVE_DATA.ST2")

    resources: list[dict[str, object]] = []
    for index, (name_record, start) in enumerate(zip(names, starts)):
        end = starts[index + 1] if index + 1 < RESOURCE_COUNT else len(eve)
        if index < RESOURCE_COUNT - 1:
            declared_size = int(boundaries[index]["delta"])
        else:
            declared_size = end - start
        if index < RESOURCE_COUNT - 1:
            expected_end = align4(start + declared_size)
            if expected_end != end:
                raise ValueError(
                    f"resource {index} boundary mismatch: "
                    f"0x{expected_end:X} != 0x{end:X}"
                )
        padding = end - start - declared_size
        if padding < 0 or padding > 3:
            raise ValueError(f"resource {index} has invalid padding {padding}")
        resources.append(
            {
                "index": index,
                "name": name_record["name"],
                "name_pool_offset": name_record["pool_offset"],
                "start_offset": start,
                "declared_size": declared_size,
                "allocation_end_offset": end,
                "allocation_size": end - start,
                "alignment_padding": padding,
                "sha256": sha256(eve[start : start + declared_size]),
            }
        )

    return {
        "format": "slayers-royal-2-eve-resource-inventory-v1",
        "basyo_sha256": sha256(basyo),
        "eve_data_sha256": sha256(eve),
        "eve_data_lba": eve_lba,
        "resource_base": {
            "location_offset": RESOURCE_BASE_LOCATION_OFFSET,
            "intra_sector_offset": RESOURCE_BASE_INTRA_SECTOR_OFFSET,
            "cd_location": base_location,
            "msf": base_msf,
            "lba": base_lba,
            "intra_sector": base_intra_sector,
        },
        "resource_count": len(resources),
        "boundary_count": len(boundaries),
        "name_pool": [NAME_POOL_START, NAME_POOL_END],
        "boundary_table_offset": BOUNDARY_TABLE_START,
        "resources": resources,
    }
