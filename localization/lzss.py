#!/usr/bin/env python3
"""Decode and encode Slayers Royal 2's resource compression format."""

from __future__ import annotations

import argparse
from pathlib import Path


HEADER_SIZE = 4
MIN_MATCH = 3
MAX_MATCH = 18
MAX_DISTANCE = 0xFFF


def decompress(data: bytes) -> bytes:
    if len(data) < HEADER_SIZE:
        raise ValueError("compressed stream is missing its size header")

    output_size = int.from_bytes(data[:HEADER_SIZE], "big") + 1
    source = HEADER_SIZE
    output = bytearray()

    while len(output) < output_size:
        if source >= len(data):
            raise ValueError("compressed stream ended before its flag byte")
        flags = data[source]
        source += 1

        for bit in range(8):
            if len(output) >= output_size:
                break
            if source >= len(data):
                raise ValueError("compressed stream ended inside a token group")

            first = data[source]
            source += 1
            if flags & (1 << bit):
                output.append(first)
                continue

            if source >= len(data):
                raise ValueError("compressed stream ended inside a back-reference")
            second = data[source]
            source += 1
            distance = (first >> 4) | (second << 4)
            length = (first & 0x0F) + MIN_MATCH
            copy_start = len(output) - distance

            # The game treats bytes before the output buffer as zero-filled.
            while copy_start < 0 and length and len(output) < output_size:
                output.append(0)
                copy_start += 1
                length -= 1
            while length and len(output) < output_size:
                if copy_start >= len(output):
                    raise ValueError(f"invalid forward back-reference at 0x{source - 2:X}")
                output.append(output[copy_start])
                copy_start += 1
                length -= 1

    return bytes(output)


def _best_match(data: bytes, position: int) -> tuple[int, int]:
    window_start = max(0, position - MAX_DISTANCE)
    best_distance = 0
    best_length = 0
    max_length = min(MAX_MATCH, len(data) - position)
    if max_length < MIN_MATCH:
        return 0, 0

    # Searching from the nearest match first gives deterministic output and
    # tends to favor overlap-friendly runs such as zero-filled glyph space.
    prefix = data[position : position + MIN_MATCH]
    candidate = data.rfind(prefix, window_start, position)
    while candidate >= window_start:
        distance = position - candidate
        length = MIN_MATCH
        while length < max_length and data[position + length] == data[position + length - distance]:
            length += 1
        if length > best_length:
            best_distance = distance
            best_length = length
            if length == max_length:
                break
        candidate = data.rfind(prefix, window_start, candidate)

    return best_distance, best_length


def compress(data: bytes) -> bytes:
    if not data:
        raise ValueError("the format cannot represent an empty output")
    if len(data) > 0x1_0000_0000:
        raise ValueError("output is too large for the four-byte size header")

    result = bytearray((len(data) - 1).to_bytes(HEADER_SIZE, "big"))
    position = 0
    while position < len(data):
        flag_offset = len(result)
        result.append(0)
        flags = 0

        for bit in range(8):
            if position >= len(data):
                break
            distance, length = _best_match(data, position)
            if length >= MIN_MATCH:
                first = ((distance & 0x0F) << 4) | (length - MIN_MATCH)
                second = distance >> 4
                result.extend((first, second))
                position += length
            else:
                flags |= 1 << bit
                result.append(data[position])
                position += 1

        result[flag_offset] = flags

    return bytes(result)


def compress_lazy(data: bytes) -> bytes:
    """Encode with one-byte lazy matching.

    Some of the larger original resources were packed with a lazy parser and
    do not fit their fixed allocations when encoded by the simpler greedy
    routine above.  If the next byte begins a strictly longer match, emit the
    current byte literally and take that match on the next token.  This keeps
    the format identical while recovering the space needed by those assets.
    """
    if not data:
        raise ValueError("the format cannot represent an empty output")
    if len(data) > 0x1_0000_0000:
        raise ValueError("output is too large for the four-byte size header")

    result = bytearray((len(data) - 1).to_bytes(HEADER_SIZE, "big"))
    position = 0
    while position < len(data):
        flag_offset = len(result)
        result.append(0)
        flags = 0

        for bit in range(8):
            if position >= len(data):
                break
            distance, length = _best_match(data, position)
            if length >= MIN_MATCH and position + 1 < len(data):
                _next_distance, next_length = _best_match(data, position + 1)
                if next_length > length:
                    length = 0
            if length >= MIN_MATCH:
                first = ((distance & 0x0F) << 4) | (length - MIN_MATCH)
                second = distance >> 4
                result.extend((first, second))
                position += length
            else:
                flags |= 1 << bit
                result.append(data[position])
                position += 1

        result[flag_offset] = flags

    return bytes(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("decode", "encode", "verify"))
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()

    source = args.input.read_bytes()
    if args.mode == "decode":
        result = decompress(source)
    elif args.mode == "encode":
        result = compress(source)
    else:
        decoded = decompress(source)
        encoded = compress(decoded)
        if decompress(encoded) != decoded:
            raise ValueError("encode/decode round trip failed")
        print(
            f"verified {args.input}: {len(source):,} compressed bytes -> "
            f"{len(decoded):,} decoded bytes -> {len(encoded):,} recompressed bytes"
        )
        return

    if args.output is None:
        parser.error(f"{args.mode} requires an output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    print(f"wrote {args.output} ({len(result):,} bytes)")


if __name__ == "__main__":
    main()
