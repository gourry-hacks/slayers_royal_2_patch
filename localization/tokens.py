#!/usr/bin/env python3
"""Dictionary compression and renderer hook for Royal 2 scene text."""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass


TOKEN_BASE = 0x0400
TOKEN_LIMIT = 0x1000
MAX_TOKENS = TOKEN_LIMIT - TOKEN_BASE
STRUCTURAL_WORDS = {0x00FD, 0x00FE, 0x00FF}

RUNTIME_BASE = 0x80150000
# Existing message pointers intentionally use +0x13A so they land two bytes
# before the corresponding AREA record. The loader itself copies AREA byte
# zero to +0x13C; dictionaries and trailers use the physical copy bias.
RUNTIME_RESOURCE_BIAS = 0x013A
RUNTIME_COPY_BIAS = 0x013C
RUNTIME_LIMIT = 0x80180000
AREA_LOCAL_CAPACITY = RUNTIME_LIMIT - RUNTIME_BASE - RUNTIME_COPY_BIAS
AREA_TRAILER_SIZE = 8
AREA_TRAILER_OFFSET = AREA_LOCAL_CAPACITY - AREA_TRAILER_SIZE
AREA_TRAILER_ADDRESS = RUNTIME_BASE + RUNTIME_COPY_BIAS + AREA_TRAILER_OFFSET
AREA_TRAILER_MAGIC = 0x54325253  # "SR2T" in little-endian memory

# EVE_HELP is copied to this fixed runtime window.  The following live object
# begins immediately after the source allocation, so the localized resource
# must retain the original size even when its text grows substantially.
GLOBAL_RUNTIME_BASE = 0x80187A00
GLOBAL_LOCAL_CAPACITY = 0x8A04
GLOBAL_TRAILER_SIZE = 8
GLOBAL_TRAILER_OFFSET = GLOBAL_LOCAL_CAPACITY - GLOBAL_TRAILER_SIZE
GLOBAL_TRAILER_ADDRESS = GLOBAL_RUNTIME_BASE + GLOBAL_TRAILER_OFFSET
GLOBAL_TRAILER_MAGIC = 0x47325253  # "SR2G" in little-endian memory

BASYO_LOAD_ADDRESS = 0x8004ACC0
FETCH_HOOK_ADDRESS = 0x8007772C
FETCH_HOOK_SIZE = 0x2C
DECODER_ADDRESS = 0x8009B200
DECODER_CAVE_SIZE = 0x270
DECODER_STATE_ADDRESS = 0x8009B400
DECODER_MAX_DEPTH = 8

MESSAGE_POINTER_ADDRESS = 0x8009FED4
MESSAGE_INDEX_ADDRESS = 0x800A22F6

# Persistent, pointer-backed exploration dialogue inside BASYO. The selector
# lives in the reclaimed text pool so the original decoder cave stays clear
# of the separately allocated battle HUD names.
EMBEDDED_BANK_START = 0x44FF0
EMBEDDED_BANK_END = 0x49254
EMBEDDED_SELECTOR_SIZE = 0x100
# The Status loader's two thunks share this allocation after the selector.
STATUS_STAGING_THUNK_OFFSET = 0x58
STATUS_STAGING_THUNK_SIZE = 0x18
EMBEDDED_TRAILER_MAGIC = 0x45325253  # SR2E

REG = {
    "zero": 0,
    "at": 1,
    "v0": 2,
    "v1": 3,
    "a0": 4,
    "a1": 5,
    "a2": 6,
    "a3": 7,
    "t0": 8,
    "t1": 9,
    "t2": 10,
    "t3": 11,
    "t4": 12,
    "t5": 13,
    "t6": 14,
    "t7": 15,
    "s1": 17,
    "t8": 24,
    "t9": 25,
    "sp": 29,
    "ra": 31,
}


def r_type(rs: int, rt: int, rd: int, shift: int, function: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shift << 6) | function


def i_type(op: int, rs: int, rt: int, immediate: int) -> int:
    return (op << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def j_type(op: int, address: int) -> int:
    return (op << 26) | ((address >> 2) & 0x03FFFFFF)


@dataclass
class Fixup:
    index: int
    kind: str
    label: str
    rs: int = 0
    rt: int = 0


class Assembler:
    def __init__(self, base: int) -> None:
        self.base = base
        self.words: list[int] = []
        self.labels: dict[str, int] = {}
        self.fixups: list[Fixup] = []

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate assembler label: {name}")
        self.labels[name] = len(self.words)

    def emit(self, word: int) -> None:
        self.words.append(word & 0xFFFFFFFF)

    def branch(self, op: int, rs: str, rt: str, label: str) -> None:
        self.fixups.append(Fixup(len(self.words), "branch", label, REG[rs], REG[rt]))
        self.emit(i_type(op, REG[rs], REG[rt], 0))

    def jump(self, op: int, label: str) -> None:
        self.fixups.append(Fixup(len(self.words), "jal" if op == 3 else "jump", label))
        self.emit(0)

    def finish(self) -> bytes:
        for fixup in self.fixups:
            target = self.labels[fixup.label]
            if fixup.kind == "branch":
                delta = target - fixup.index - 1
                if not -0x8000 <= delta <= 0x7FFF:
                    raise ValueError(f"branch to {fixup.label} is out of range")
                op = self.words[fixup.index] >> 26
                self.words[fixup.index] = i_type(op, fixup.rs, fixup.rt, delta)
            else:
                op = 3 if fixup.kind == "jal" else 2
                self.words[fixup.index] = j_type(op, self.base + target * 4)
        return struct.pack(f"<{len(self.words)}I", *self.words)


def _is_literal(word: int) -> bool:
    return 0 < word < TOKEN_BASE and word not in STRUCTURAL_WORDS


def raw_script_controls(words: list[int]) -> list[int]:
    """Controls that retail script scanners must see without token expansion."""
    return [word for word in words if word == 0 or word in STRUCTURAL_WORDS or word >= 0x8000]


def _literal_runs(words: list[int]) -> list[tuple[int, ...]]:
    result: list[tuple[int, ...]] = []
    start = 0
    while start < len(words):
        if not _is_literal(words[start]):
            start += 1
            continue
        end = start + 1
        while end < len(words) and _is_literal(words[end]):
            end += 1
        result.append(tuple(words[start:end]))
        start = end
    return result


def _make_trie(sequences: set[tuple[int, ...]]) -> dict:
    root: dict = {}
    for sequence in sequences:
        node = root
        for word in sequence:
            node = node.setdefault(word, {})
        node[None] = sequence
    return root


def _tokenize_run(run: tuple[int, ...], trie: dict) -> list[int | tuple[int, ...]]:
    size = len(run)
    costs = [0] * (size + 1)
    choices: list[tuple[int, ...] | None] = [None] * size
    for start in range(size - 1, -1, -1):
        costs[start] = 1 + costs[start + 1]
        node = trie
        end = start
        while end < size and run[end] in node:
            node = node[run[end]]
            end += 1
            sequence = node.get(None)
            if sequence is not None and 1 + costs[end] < costs[start]:
                costs[start] = 1 + costs[end]
                choices[start] = sequence

    result: list[int | tuple[int, ...]] = []
    cursor = 0
    while cursor < size:
        sequence = choices[cursor]
        if sequence is None:
            result.append(run[cursor])
            cursor += 1
        else:
            result.append(sequence)
            cursor += len(sequence)
    return result


def _candidate_sequences(
    runs: list[tuple[int, ...]], space_glyph: int
) -> set[tuple[int, ...]]:
    counts: Counter[tuple[int, ...]] = Counter()
    for run in runs:
        boundaries = [0]
        boundaries.extend(index + 1 for index, word in enumerate(run) if word == space_glyph)
        if boundaries[-1] != len(run):
            boundaries.append(len(run))
        for first in range(len(boundaries) - 1):
            for last in range(first + 1, min(len(boundaries), first + 6)):
                sequence = run[boundaries[first] : boundaries[last]]
                if 3 <= len(sequence) <= 64:
                    counts[sequence] += 1

    scored = []
    for sequence, occurrences in counts.items():
        # One table word, one length word, and the literal expansion are the
        # conservative dictionary cost before recursive entry compression.
        score = occurrences * (len(sequence) - 1) - (len(sequence) + 2)
        if score > 0:
            scored.append((score, len(sequence), sequence))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return {sequence for _score, _length, sequence in scored[:MAX_TOKENS]}


@dataclass
class TokenDictionary:
    sequences: list[tuple[int, ...]]
    encoded_entries: list[list[int]]
    encoded_bodies: list[list[int]]
    blob: bytes
    report: dict[str, object]


def parse_token_dictionary(blob: bytes) -> list[list[int]]:
    """Parse and validate one serialized renderer dictionary."""
    if len(blob) < 2:
        raise ValueError("token dictionary is truncated")
    count = struct.unpack_from("<H", blob, 0)[0]
    if count > MAX_TOKENS:
        raise ValueError(f"token dictionary has too many entries: {count}")
    table_end = 2 + count * 2
    if table_end > len(blob):
        raise ValueError("token dictionary offset table is truncated")
    offsets = list(struct.unpack_from(f"<{count}H", blob, 2)) if count else []
    entries: list[list[int]] = []
    for index, word_offset in enumerate(offsets):
        byte_offset = word_offset * 2
        if byte_offset < table_end or byte_offset + 2 > len(blob):
            raise ValueError(f"token {TOKEN_BASE + index:#x} has an invalid offset")
        length = struct.unpack_from("<H", blob, byte_offset)[0]
        end = byte_offset + 2 + length * 2
        if end > len(blob):
            raise ValueError(f"token {TOKEN_BASE + index:#x} is truncated")
        entry = list(struct.unpack_from(f"<{length}H", blob, byte_offset + 2))
        for child in entry:
            if TOKEN_BASE <= child < TOKEN_LIMIT and child - TOKEN_BASE >= index:
                raise ValueError(
                    f"token {TOKEN_BASE + index:#x} has a forward/self reference "
                    f"to {child:#x}"
                )
        entries.append(entry)
    return entries


def expand_token_words(
    words: list[int], entries: list[list[int]], maximum_depth: int = DECODER_MAX_DEPTH
) -> list[int]:
    """Expand token IDs exactly as the runtime renderer hook does."""
    output: list[int] = []

    def expand(word: int, depth: int) -> None:
        if not TOKEN_BASE <= word < TOKEN_LIMIT:
            output.append(word)
            return
        if depth >= maximum_depth:
            raise ValueError("token expansion exceeds the renderer stack depth")
        index = word - TOKEN_BASE
        if index >= len(entries):
            raise ValueError(f"undefined token {word:#x}")
        for child in entries[index]:
            expand(child, depth + 1)

    for word in words:
        expand(word, 0)
    return output


def read_area_dictionary(area: bytes) -> tuple[list[list[int]], dict[str, int]]:
    """Read the dictionary referenced by a fixed-capacity AREA trailer."""
    if len(area) != AREA_LOCAL_CAPACITY:
        raise ValueError(
            f"tokenized AREA has size {len(area):#x}, expected {AREA_LOCAL_CAPACITY:#x}"
        )
    dictionary_address, magic = struct.unpack_from("<II", area, AREA_TRAILER_OFFSET)
    if magic != AREA_TRAILER_MAGIC:
        raise ValueError(f"tokenized AREA trailer has invalid magic {magic:#x}")
    dictionary_offset = dictionary_address - RUNTIME_BASE - RUNTIME_COPY_BIAS
    if not 0 <= dictionary_offset < AREA_TRAILER_OFFSET:
        raise ValueError(f"token dictionary address is outside AREA: {dictionary_address:#x}")
    entries = parse_token_dictionary(area[dictionary_offset:AREA_TRAILER_OFFSET])
    used_end = 2 + len(entries) * 2
    if entries:
        offsets = struct.unpack_from(f"<{len(entries)}H", area, dictionary_offset + 2)
        used_end = max(
            word_offset * 2 + 2 + len(entry) * 2
            for word_offset, entry in zip(offsets, entries, strict=True)
        )
    padding = area[dictionary_offset + used_end : AREA_TRAILER_OFFSET]
    if any(padding):
        raise ValueError("tokenized AREA has nonzero dictionary padding")
    return entries, {
        "dictionary_offset": dictionary_offset,
        "dictionary_address": dictionary_address,
        "dictionary_size": used_end,
        "token_count": len(entries),
        "trailer_offset": AREA_TRAILER_OFFSET,
    }


def read_global_dictionary(resource: bytes) -> tuple[list[list[int]], dict[str, int]]:
    """Read the dictionary stored in the fixed-size EVE_HELP allocation."""
    if len(resource) != GLOBAL_LOCAL_CAPACITY:
        raise ValueError(
            f"tokenized EVE_HELP has size {len(resource):#x}, "
            f"expected {GLOBAL_LOCAL_CAPACITY:#x}"
        )
    dictionary_address, magic = struct.unpack_from(
        "<II", resource, GLOBAL_TRAILER_OFFSET
    )
    if magic != GLOBAL_TRAILER_MAGIC:
        raise ValueError(f"EVE_HELP trailer has invalid magic {magic:#x}")
    dictionary_offset = dictionary_address - GLOBAL_RUNTIME_BASE
    if not 0 <= dictionary_offset < GLOBAL_TRAILER_OFFSET:
        raise ValueError(
            f"EVE_HELP dictionary address is outside the resource: "
            f"{dictionary_address:#x}"
        )
    entries = parse_token_dictionary(
        resource[dictionary_offset:GLOBAL_TRAILER_OFFSET]
    )
    used_end = 2 + len(entries) * 2
    if entries:
        offsets = struct.unpack_from(
            f"<{len(entries)}H", resource, dictionary_offset + 2
        )
        used_end = max(
            word_offset * 2 + 2 + len(entry) * 2
            for word_offset, entry in zip(offsets, entries, strict=True)
        )
    padding = resource[
        dictionary_offset + used_end : GLOBAL_TRAILER_OFFSET
    ]
    if any(padding):
        raise ValueError("tokenized EVE_HELP has nonzero dictionary padding")
    return entries, {
        "dictionary_offset": dictionary_offset,
        "dictionary_address": dictionary_address,
        "dictionary_size": used_end,
        "token_count": len(entries),
        "trailer_offset": GLOBAL_TRAILER_OFFSET,
    }


def build_token_dictionary(
    bodies: list[list[int]], space_glyph: int
) -> TokenDictionary:
    runs = [run for body in bodies for run in _literal_runs(body)]
    selected = _candidate_sequences(runs, space_glyph)

    for _iteration in range(16):
        trie = _make_trie(selected)
        uses: Counter[tuple[int, ...]] = Counter(
            value
            for run in runs
            for value in _tokenize_run(run, trie)
            if isinstance(value, tuple)
        )
        retained = {
            sequence
            for sequence in selected
            if uses[sequence] * (len(sequence) - 1) > len(sequence) + 2
        }
        if retained == selected:
            break
        selected = retained
    else:
        raise AssertionError("token dictionary pruning did not converge")

    sequences = sorted(selected, key=lambda value: (len(value), value))
    token_ids = {sequence: TOKEN_BASE + index for index, sequence in enumerate(sequences)}
    if len(sequences) > MAX_TOKENS:
        raise AssertionError("token dictionary exceeds the reserved ID range")

    encoded_entries: list[list[int]] = []
    prior: set[tuple[int, ...]] = set()
    for sequence in sequences:
        encoded = [
            token_ids[value] if isinstance(value, tuple) else value
            for value in _tokenize_run(sequence, _make_trie(prior))
        ]
        encoded_entries.append(encoded)
        prior.add(sequence)

    trie = _make_trie(set(sequences))
    encoded_bodies: list[list[int]] = []
    token_uses: Counter[int] = Counter()
    for body in bodies:
        encoded: list[int] = []
        cursor = 0
        while cursor < len(body):
            if not _is_literal(body[cursor]):
                encoded.append(body[cursor])
                cursor += 1
                continue
            end = cursor + 1
            while end < len(body) and _is_literal(body[end]):
                end += 1
            for value in _tokenize_run(tuple(body[cursor:end]), trie):
                word = token_ids[value] if isinstance(value, tuple) else value
                encoded.append(word)
                if TOKEN_BASE <= word < TOKEN_LIMIT:
                    token_uses[word] += 1
            cursor = end
        encoded_bodies.append(encoded)

    offsets: list[int] = []
    dictionary_words: list[int] = [len(sequences), *([0] * len(sequences))]
    for index, entry in enumerate(encoded_entries):
        offsets.append(len(dictionary_words))
        dictionary_words.extend([len(entry), *entry])
        dictionary_words[1 + index] = offsets[-1]
    if len(dictionary_words) > 0xFFFF or any(offset > 0xFFFF for offset in offsets):
        raise ValueError("token dictionary offsets exceed 16 bits")

    def expand(word: int, depth: int = 0) -> tuple[int, ...]:
        if not TOKEN_BASE <= word < TOKEN_LIMIT:
            return (word,)
        if depth >= DECODER_MAX_DEPTH:
            raise ValueError("token expansion exceeds the renderer stack depth")
        index = word - TOKEN_BASE
        if index >= len(encoded_entries):
            raise ValueError(f"undefined token {word:#x}")
        output: list[int] = []
        for child in encoded_entries[index]:
            output.extend(expand(child, depth + 1))
        return tuple(output)

    maximum_depth = 0

    def depth(word: int) -> int:
        if not TOKEN_BASE <= word < TOKEN_LIMIT:
            return 0
        return 1 + max((depth(value) for value in encoded_entries[word - TOKEN_BASE]), default=0)

    for index, sequence in enumerate(sequences):
        token = TOKEN_BASE + index
        if expand(token) != sequence:
            raise AssertionError(f"recursive token {token:#x} does not round-trip")
        maximum_depth = max(maximum_depth, depth(token))

    plain_words = sum(len(body) for body in bodies)
    encoded_words = sum(len(body) for body in encoded_bodies)
    report = {
        "token_count": len(sequences),
        "token_uses": sum(token_uses.values()),
        "plain_body_words": plain_words,
        "encoded_body_words": encoded_words,
        "dictionary_words": len(dictionary_words),
        "total_compressed_words": encoded_words + len(dictionary_words),
        "saved_words": plain_words - encoded_words - len(dictionary_words),
        "maximum_expansion_depth": maximum_depth,
    }
    return TokenDictionary(
        sequences=sequences,
        encoded_entries=encoded_entries,
        encoded_bodies=encoded_bodies,
        blob=struct.pack(f"<{len(dictionary_words)}H", *dictionary_words),
        report=report,
    )


def build_bpe_token_dictionary(bodies: list[list[int]]) -> TokenDictionary:
    """Build a compact recursive pair dictionary for the fixed EVE_HELP bank.

    Scene dictionaries favor whole-word phrases because they have ample local
    storage.  EVE_HELP needs a denser grammar: each selected pair costs four
    dictionary words (offset, length, and two children), so a pair is retained
    only when at least five non-overlapping uses make the complete resource
    smaller.
    """
    encoded_bodies = [list(body) for body in bodies]
    encoded_entries: list[list[int]] = []
    depths: dict[int, int] = {}

    while len(encoded_entries) < MAX_TOKENS:
        counts: Counter[tuple[int, int]] = Counter()
        for body in encoded_bodies:
            counts.update(
                (left, right)
                for left, right in zip(body, body[1:])
                if (_is_literal(left) or TOKEN_BASE <= left < TOKEN_LIMIT)
                and (_is_literal(right) or TOKEN_BASE <= right < TOKEN_LIMIT)
            )

        selected: tuple[tuple[int, int], int, int] | None = None
        for pair, raw_uses in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        ):
            depth = 1 + max(depths.get(pair[0], 0), depths.get(pair[1], 0))
            if depth > DECODER_MAX_DEPTH or raw_uses <= 4:
                continue
            uses = 0
            for body in encoded_bodies:
                cursor = 0
                while cursor + 1 < len(body):
                    if (body[cursor], body[cursor + 1]) == pair:
                        uses += 1
                        cursor += 2
                    else:
                        cursor += 1
            if uses > 4:
                selected = pair, uses, depth
                break
        if selected is None:
            break

        pair, _uses, depth = selected
        token = TOKEN_BASE + len(encoded_entries)
        encoded_entries.append(list(pair))
        depths[token] = depth
        for body_index, body in enumerate(encoded_bodies):
            replaced: list[int] = []
            cursor = 0
            while cursor < len(body):
                if (
                    cursor + 1 < len(body)
                    and (body[cursor], body[cursor + 1]) == pair
                ):
                    replaced.append(token)
                    cursor += 2
                else:
                    replaced.append(body[cursor])
                    cursor += 1
            encoded_bodies[body_index] = replaced

    # Portrait preloading (BASYO 0x80079114) scans the stored words directly.
    # Hiding a 9xxx/Axxx command in a token omits that portrait from its load
    # list; the renderer later waits forever for the missing portrait. Other
    # state/effect commands and zero joins likewise stay visible to scanners.
    for plain, stored in zip(bodies, encoded_bodies, strict=True):
        if raw_script_controls(plain) != raw_script_controls(stored):
            raise ValueError("BPE compression hid or reordered a script control")

    dictionary_words: list[int] = [
        len(encoded_entries),
        *([0] * len(encoded_entries)),
    ]
    for index, entry in enumerate(encoded_entries):
        dictionary_words[1 + index] = len(dictionary_words)
        dictionary_words.extend([len(entry), *entry])
    if len(dictionary_words) > 0xFFFF:
        raise ValueError("EVE_HELP token dictionary offsets exceed 16 bits")

    def expand(word: int, depth: int = 0) -> tuple[int, ...]:
        if not TOKEN_BASE <= word < TOKEN_BASE + len(encoded_entries):
            return (word,)
        if depth >= DECODER_MAX_DEPTH:
            raise ValueError("EVE_HELP token expansion exceeds the renderer depth")
        output: list[int] = []
        for child in encoded_entries[word - TOKEN_BASE]:
            output.extend(expand(child, depth + 1))
        return tuple(output)

    expanded_sequences = [
        expand(TOKEN_BASE + index) for index in range(len(encoded_entries))
    ]
    for plain, encoded in zip(bodies, encoded_bodies, strict=True):
        if list(expand_token_words(encoded, encoded_entries)) != plain:
            raise AssertionError("EVE_HELP token dictionary does not round-trip")

    plain_words = sum(len(body) for body in bodies)
    encoded_words = sum(len(body) for body in encoded_bodies)
    report = {
        "strategy": "recursive_byte_pair",
        "token_count": len(encoded_entries),
        "token_uses": sum(
            TOKEN_BASE <= word < TOKEN_BASE + len(encoded_entries)
            for body in encoded_bodies
            for word in body
        ),
        "plain_body_words": plain_words,
        "encoded_body_words": encoded_words,
        "dictionary_words": len(dictionary_words),
        "total_compressed_words": encoded_words + len(dictionary_words),
        "saved_words": plain_words - encoded_words - len(dictionary_words),
        "maximum_expansion_depth": max(depths.values(), default=0),
    }
    return TokenDictionary(
        sequences=expanded_sequences,
        encoded_entries=encoded_entries,
        encoded_bodies=encoded_bodies,
        blob=struct.pack(f"<{len(dictionary_words)}H", *dictionary_words),
        report=report,
    )


def append_area_dictionary(area: bytes, dictionary: bytes) -> tuple[bytes, dict[str, int]]:
    dictionary_offset = (len(area) + 1) & ~1
    dictionary_end = dictionary_offset + len(dictionary)
    if dictionary_end > AREA_TRAILER_OFFSET:
        raise ValueError(
            f"compressed AREA plus dictionary ends at {dictionary_end:#x}, "
            f"beyond trailer {AREA_TRAILER_OFFSET:#x}"
        )
    dictionary_address = RUNTIME_BASE + RUNTIME_COPY_BIAS + dictionary_offset
    output = bytearray(area)
    output.extend(b"\x00" * (dictionary_offset - len(output)))
    output.extend(dictionary)
    output.extend(b"\x00" * (AREA_TRAILER_OFFSET - len(output)))
    output.extend(struct.pack("<II", dictionary_address, AREA_TRAILER_MAGIC))
    if len(output) != AREA_LOCAL_CAPACITY:
        raise AssertionError("tokenized AREA does not occupy the fixed local capacity")
    return bytes(output), {
        "dictionary_offset": dictionary_offset,
        "dictionary_address": dictionary_address,
        "dictionary_size": len(dictionary),
        "trailer_offset": AREA_TRAILER_OFFSET,
        "trailer_address": AREA_TRAILER_ADDRESS,
        "output_size": len(output),
    }


def append_global_dictionary(
    resource: bytes, dictionary: bytes
) -> tuple[bytes, dict[str, int]]:
    """Pad compressed EVE_HELP data and its dictionary to the source capacity."""
    dictionary_offset = (len(resource) + 1) & ~1
    dictionary_end = dictionary_offset + len(dictionary)
    if dictionary_end > GLOBAL_TRAILER_OFFSET:
        raise ValueError(
            f"compressed EVE_HELP plus dictionary ends at {dictionary_end:#x}, "
            f"beyond trailer {GLOBAL_TRAILER_OFFSET:#x}"
        )
    dictionary_address = GLOBAL_RUNTIME_BASE + dictionary_offset
    output = bytearray(resource)
    output.extend(b"\x00" * (dictionary_offset - len(output)))
    output.extend(dictionary)
    output.extend(b"\x00" * (GLOBAL_TRAILER_OFFSET - len(output)))
    output.extend(struct.pack("<II", dictionary_address, GLOBAL_TRAILER_MAGIC))
    if len(output) != GLOBAL_LOCAL_CAPACITY:
        raise AssertionError("tokenized EVE_HELP does not retain its fixed capacity")
    return bytes(output), {
        "dictionary_offset": dictionary_offset,
        "dictionary_address": dictionary_address,
        "dictionary_size": len(dictionary),
        "trailer_offset": GLOBAL_TRAILER_OFFSET,
        "trailer_address": GLOBAL_TRAILER_ADDRESS,
        "output_size": len(output),
    }


def decoder_blobs(embedded: bool = False) -> tuple[bytes, bytes]:
    a = Assembler(DECODER_ADDRESS)
    z = "zero"
    state_hi = (DECODER_STATE_ADDRESS + 0x8000) >> 16
    state_lo = DECODER_STATE_ADDRESS & 0xFFFF

    def emit_i(op: int, rt: str, rs: str, value: int) -> None:
        a.emit(i_type(op, REG[rs], REG[rt], value))

    def lui(rt: str, value: int) -> None:
        a.emit(i_type(0x0F, 0, REG[rt], value))

    def ori(rt: str, rs: str, value: int) -> None:
        emit_i(0x0D, rt, rs, value)

    def addiu(rt: str, rs: str, value: int) -> None:
        emit_i(0x09, rt, rs, value)

    def sltiu(rt: str, rs: str, value: int) -> None:
        emit_i(0x0B, rt, rs, value)

    def mem(op: int, rt: str, offset: int, base: str) -> None:
        a.emit(i_type(op, REG[base], REG[rt], offset))

    def addu(rd: str, rs: str, rt: str) -> None:
        a.emit(r_type(REG[rs], REG[rt], REG[rd], 0, 0x21))

    def shift_left(rd: str, rt: str, amount: int) -> None:
        a.emit(r_type(0, REG[rt], REG[rd], amount, 0x00))

    def sltu(rd: str, rs: str, rt: str) -> None:
        a.emit(r_type(REG[rs], REG[rt], REG[rd], 0, 0x2B))

    def beq(rs: str, rt: str, label: str) -> None:
        a.branch(0x04, rs, rt, label)

    def bne(rs: str, rt: str, label: str) -> None:
        a.branch(0x05, rs, rt, label)

    def jump(label: str) -> None:
        a.jump(2, label)

    def nop() -> None:
        a.emit(0)

    lui("t0", (MESSAGE_POINTER_ADDRESS + 0x8000) >> 16)
    mem(0x29, z, 0x2302, "t0")
    mem(0x23, "t1", MESSAGE_POINTER_ADDRESS & 0xFFFF, "t0")
    lui("t2", state_hi)
    addiu("t2", "t2", state_lo)
    mem(0x23, "t3", 0, "t2")
    nop()
    beq("t3", z, "fetch_source")
    nop()
    mem(0x23, "t4", 4, "t2")
    nop()
    beq("t4", "t1", "check_owner_index")
    nop()
    mem(0x2B, z, 0, "t2")
    jump("fetch_source")
    nop()

    a.label("check_owner_index")
    mem(0x25, "t4", MESSAGE_INDEX_ADDRESS & 0xFFFF, "t0")
    mem(0x25, "t5", 8, "t2")
    nop()
    beq("t4", "t5", "read_stack")
    nop()
    mem(0x2B, z, 0, "t2")

    a.label("fetch_source")
    mem(0x25, "t3", MESSAGE_INDEX_ADDRESS & 0xFFFF, "t0")
    nop()
    shift_left("t4", "t3", 1)
    addu("t4", "t4", "t1")
    mem(0x25, "v0", 0, "t4")
    addiu("t3", "t3", 1)
    mem(0x29, "t3", MESSAGE_INDEX_ADDRESS & 0xFFFF, "t0")
    addiu("t4", "v0", -TOKEN_BASE)
    sltiu("t5", "t4", TOKEN_LIMIT - TOKEN_BASE)
    beq("t5", z, "return")
    nop()
    jump("expand_token")
    nop()

    a.label("read_stack")
    addiu("t3", "t3", -1)
    shift_left("t4", "t3", 3)
    addiu("t5", "t2", 16)
    addu("t5", "t5", "t4")
    mem(0x23, "t6", 0, "t5")
    mem(0x25, "t7", 4, "t5")
    nop()
    mem(0x25, "v0", 0, "t6")
    addiu("t6", "t6", 2)
    addiu("t7", "t7", -1)
    mem(0x2B, "t6", 0, "t5")
    mem(0x29, "t7", 4, "t5")
    bne("t7", z, "check_token")
    nop()
    mem(0x2B, "t3", 0, "t2")

    a.label("check_token")
    addiu("t4", "v0", -TOKEN_BASE)
    sltiu("t5", "t4", TOKEN_LIMIT - TOKEN_BASE)
    beq("t5", z, "return")
    nop()

    a.label("expand_token")
    lui("t5", GLOBAL_RUNTIME_BASE >> 16)
    ori("t5", "t5", GLOBAL_RUNTIME_BASE & 0xFFFF)
    sltu("t6", "t1", "t5")
    bne("t6", z, "area_dictionary")
    nop()
    lui("t5", (GLOBAL_RUNTIME_BASE + GLOBAL_LOCAL_CAPACITY + 0x8000) >> 16)
    addiu("t5", "t5", (GLOBAL_RUNTIME_BASE + GLOBAL_LOCAL_CAPACITY) & 0xFFFF)
    sltu("t6", "t1", "t5")
    bne("t6", z, "global_dictionary")
    nop()

    a.label("area_dictionary")
    if embedded:
        a.emit(j_type(2, BASYO_LOAD_ADDRESS + EMBEDDED_BANK_START))
        nop()
    else:
        lui("t5", RUNTIME_LIMIT >> 16)
        lui("t8", AREA_TRAILER_MAGIC >> 16)
        ori("t8", "t8", AREA_TRAILER_MAGIC & 0xFFFF)
        jump("validate_dictionary")
        nop()

    a.label("global_dictionary")
    lui("t8", GLOBAL_TRAILER_MAGIC >> 16)
    ori("t8", "t8", GLOBAL_TRAILER_MAGIC & 0xFFFF)

    a.label("validate_dictionary")
    mem(0x23, "t6", -4, "t5")
    mem(0x23, "t7", -8, "t5")
    bne("t6", "t8", "return")
    nop()
    mem(0x25, "t8", 0, "t7")
    nop()
    sltu("t9", "t4", "t8")
    beq("t9", z, "return")
    shift_left("t4", "t4", 1)
    addu("t8", "t7", "t4")
    mem(0x25, "t8", 2, "t8")
    nop()
    shift_left("t8", "t8", 1)
    addu("t8", "t8", "t7")
    mem(0x25, "t9", 0, "t8")
    addiu("t8", "t8", 2)
    mem(0x23, "t3", 0, "t2")
    nop()
    beq("t9", z, "return")
    sltiu("t4", "t3", DECODER_MAX_DEPTH)
    beq("t4", z, "return")
    shift_left("t4", "t3", 3)
    addiu("t5", "t2", 16)
    addu("t5", "t5", "t4")
    mem(0x2B, "t8", 0, "t5")
    mem(0x29, "t9", 4, "t5")
    addiu("t3", "t3", 1)
    mem(0x2B, "t3", 0, "t2")
    mem(0x2B, "t1", 4, "t2")
    mem(0x25, "t4", MESSAGE_INDEX_ADDRESS & 0xFFFF, "t0")
    nop()
    mem(0x29, "t4", 8, "t2")
    jump("read_stack")
    nop()

    a.label("return")
    a.emit(r_type(REG["ra"], 0, 0, 0, 0x08))
    nop()

    blob = a.finish()
    if len(blob) > DECODER_STATE_ADDRESS - DECODER_ADDRESS:
        raise ValueError(
            f"token decoder is {len(blob):#x} bytes and overlaps its state block"
        )
    selector = b""
    if embedded:
        s = Assembler(BASYO_LOAD_ADDRESS + EMBEDDED_BANK_START)

        def constant(register: str, value: int) -> None:
            s.emit(i_type(0x0F, 0, REG[register], value >> 16))
            s.emit(i_type(0x0D, REG[register], REG[register], value & 0xFFFF))

        constant("t5", BASYO_LOAD_ADDRESS + EMBEDDED_BANK_START)
        s.emit(r_type(REG["t1"], REG["t5"], REG["t6"], 0, 0x2B))
        s.branch(0x05, "t6", "zero", "area")
        s.emit(0)
        constant("t5", BASYO_LOAD_ADDRESS + 0x534D4)
        s.emit(r_type(REG["t1"], REG["t5"], REG["t6"], 0, 0x2B))
        s.branch(0x04, "t6", "zero", "area")
        s.emit(0)
        constant("t5", BASYO_LOAD_ADDRESS + EMBEDDED_BANK_END)
        constant("t8", EMBEDDED_TRAILER_MAGIC)
        s.jump(2, "done")
        s.emit(0)
        s.label("area")
        constant("t5", RUNTIME_LIMIT)
        constant("t8", AREA_TRAILER_MAGIC)
        s.label("done")
        s.emit(j_type(2, DECODER_ADDRESS + a.labels["validate_dictionary"] * 4))
        s.emit(0)
        selector = s.finish()
        if len(selector) > STATUS_STAGING_THUNK_OFFSET:
            raise ValueError("embedded dictionary selector overlaps Status staging thunks")
    return blob, selector


def decoder_blob() -> bytes:
    return decoder_blobs()[0]


def patch_basyo_decoder(basyo: bytes, embedded: bool = False) -> tuple[bytes, dict[str, object]]:
    hook_offset = FETCH_HOOK_ADDRESS - BASYO_LOAD_ADDRESS
    cave_offset = DECODER_ADDRESS - BASYO_LOAD_ADDRESS
    state_offset = DECODER_STATE_ADDRESS - BASYO_LOAD_ADDRESS
    original_hook = bytes.fromhex(
        "0a80023c022340a40a80023cf6226396d4fe448c4010030021104400"
        "0000429401006324f62263a6dc3722a6"
    )
    if len(original_hook) != FETCH_HOOK_SIZE:
        raise AssertionError("token fetch signature has the wrong size")
    if basyo[hook_offset : hook_offset + FETCH_HOOK_SIZE] != original_hook:
        raise ValueError("BASYO token-fetch hook does not match the proven source")
    if any(basyo[cave_offset : cave_offset + DECODER_CAVE_SIZE]):
        raise ValueError("BASYO token-decoder cave is not empty")

    decoder, selector = decoder_blobs(embedded)
    store_resolved_glyph = i_type(0x29, REG["s1"], REG["v0"], 0x37DC)
    hook_words = [
        j_type(3, DECODER_ADDRESS),
        0,
        store_resolved_glyph,
        *([0] * (FETCH_HOOK_SIZE // 4 - 3)),
    ]
    hook = struct.pack(f"<{len(hook_words)}I", *hook_words)
    output = bytearray(basyo)
    output[hook_offset : hook_offset + len(hook)] = hook
    output[cave_offset : cave_offset + len(decoder)] = decoder
    if embedded:
        output[EMBEDDED_BANK_START:EMBEDDED_BANK_START + len(selector)] = selector
    output[state_offset : state_offset + 16 + DECODER_MAX_DEPTH * 8] = b"\x00" * (
        16 + DECODER_MAX_DEPTH * 8
    )
    return bytes(output), {
        "hook_address": FETCH_HOOK_ADDRESS,
        "hook_size": FETCH_HOOK_SIZE,
        "decoder_address": DECODER_ADDRESS,
        "decoder_size": len(decoder),
        "state_address": DECODER_STATE_ADDRESS,
        "state_size": 16 + DECODER_MAX_DEPTH * 8,
        "maximum_depth": DECODER_MAX_DEPTH,
        "embedded_dictionary": embedded,
    }
