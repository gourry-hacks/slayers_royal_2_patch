"""Proven AREA pointer relocation, vendored from the English builder."""
from __future__ import annotations
import hashlib
import struct
from dataclasses import dataclass, field
RUNTIME_BASE = 0x80150000
RUNTIME_LIMIT = 0x80180000
# The named AREA starts signature+0x0C, while RUNTIME_BASE maps to
# signature-0x12E.  Therefore local AREA offset zero is runtime +0x13A.
RUNTIME_RESOURCE_BIAS = 0x13A
SCENE_RESOURCE_FIRST = 1
SCENE_RESOURCE_COUNT = 21


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


@dataclass(frozen=True)
class Edit:
    """Replace one half-open source interval.

    ``anchors`` maps old offsets relative to ``start`` to new offsets relative
    to the replacement start.  Offset zero and the interval end are handled
    automatically.  Interior runtime-pointer targets require explicit entries.
    """

    start: int
    end: int
    replacement: bytes
    label: str
    anchors: dict[int, int] = field(default_factory=dict)

    def validate(self, source_size: int) -> None:
        if not 0 <= self.start < self.end <= source_size:
            raise ValueError(
                f"invalid edit {self.label}: 0x{self.start:X}..0x{self.end:X}"
            )
        old_size = self.end - self.start
        for old, new in self.anchors.items():
            if not 0 < old < old_size:
                raise ValueError(f"{self.label}: old anchor {old:#x} is not interior")
            if not 0 <= new <= len(self.replacement):
                raise ValueError(f"{self.label}: new anchor {new:#x} is out of range")


class OffsetMap:
    def __init__(self, source_size: int, edits: list[Edit]) -> None:
        self.source_size = source_size
        self.edits = sorted(edits, key=lambda edit: edit.start)
        previous_end = 0
        for edit in self.edits:
            edit.validate(source_size)
            if edit.start < previous_end:
                raise ValueError(f"overlapping edit: {edit.label}")
            previous_end = edit.end

    @property
    def output_size(self) -> int:
        return self.map_offset(self.source_size, "resource end")

    def map_offset(self, old: int, context: str) -> int:
        if not 0 <= old <= self.source_size:
            raise ValueError(f"{context}: source offset {old:#x} is outside AREA")
        delta = 0
        for edit in self.edits:
            new_start = edit.start + delta
            if old < edit.start:
                return old + delta
            if old == edit.start:
                return new_start
            if old < edit.end:
                relative = old - edit.start
                if relative not in edit.anchors:
                    raise ValueError(
                        f"{context}: pointer enters {edit.label} at unmodeled "
                        f"interior offset {relative:#x}"
                    )
                return new_start + edit.anchors[relative]
            delta += len(edit.replacement) - (edit.end - edit.start)
            if old == edit.end:
                return edit.end + delta
        return old + delta

    def apply(self, source: bytes) -> bytearray:
        if len(source) != self.source_size:
            raise ValueError("AREA source size changed after offset map construction")
        output = bytearray()
        cursor = 0
        for edit in self.edits:
            output.extend(source[cursor : edit.start])
            output.extend(edit.replacement)
            cursor = edit.end
        output.extend(source[cursor:])
        if len(output) != self.output_size:
            raise AssertionError("transformed AREA size does not match offset map")
        return output


def runtime_pointer_sites(area: bytes) -> list[tuple[int, int]]:
    """Return aligned pointer sites and local targets validated for this AREA."""
    result: list[tuple[int, int]] = []
    for source in range(0, len(area) - 3, 4):
        absolute = u32(area, source)
        if not RUNTIME_BASE <= absolute < RUNTIME_LIMIT:
            continue
        target = absolute - RUNTIME_BASE - RUNTIME_RESOURCE_BIAS
        # A few AREA tables legitimately point just before/after their named
        # allocation. They are not affected by internal edits and are retained
        # verbatim; only locally owned targets are relocation candidates.
        if 0 <= target < len(area):
            result.append((source, target))
    return result


def transform_area(area: bytes, edits: list[Edit]) -> tuple[bytes, dict[str, object]]:
    offsets = OffsetMap(len(area), edits)
    pointers = runtime_pointer_sites(area)
    output = offsets.apply(area)

    relocated: list[dict[str, int]] = []
    for old_source, old_target in pointers:
        new_source = offsets.map_offset(old_source, f"pointer source {old_source:#x}")
        new_target = offsets.map_offset(old_target, f"pointer target {old_target:#x}")
        absolute = RUNTIME_BASE + RUNTIME_RESOURCE_BIAS + new_target
        if not RUNTIME_BASE <= absolute < RUNTIME_LIMIT:
            raise ValueError(f"relocated pointer leaves runtime window: {absolute:#x}")
        struct.pack_into("<I", output, new_source, absolute)
        relocated.append(
            {
                "old_source": old_source,
                "new_source": new_source,
                "old_target": old_target,
                "new_target": new_target,
                "absolute": absolute,
            }
        )

    for pointer in relocated:
        if u32(output, pointer["new_source"]) != pointer["absolute"]:
            raise AssertionError("runtime pointer writeback verification failed")

    report: dict[str, object] = {
        "source_size": len(area),
        "output_size": len(output),
        "source_sha256": sha256(area),
        "output_sha256": sha256(output),
        "edit_count": len(edits),
        "runtime_pointer_count": len(pointers),
        "relocated_pointer_count": sum(
            pointer["old_source"] != pointer["new_source"]
            or pointer["old_target"] != pointer["new_target"]
            for pointer in relocated
        ),
    }
    return bytes(output), report
