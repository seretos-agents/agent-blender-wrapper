#!/usr/bin/env python3
"""Minimal binary FBX 7.x reader for verifying export node transforms.

Reads the small subset of the binary FBX format needed to check the claims
this skill makes about an export: `GlobalSettings.UnitScaleFactor` /
`UpAxis`, and every `Model` node's `Lcl Translation` / `Lcl Rotation` /
`Lcl Scaling`. Stdlib only (`struct` + `zlib`), so it runs under any Python 3
outside Blender -- no bpy, no FBX SDK, no third-party parser.

Usage:
    python verify_fbx.py <path-to-export.fbx>

What to look for in the output:
    - Every Model's scale should print as (1.0, 1.0, 1.0) -- the unit
      conversion belongs in GlobalSettings.UnitScaleFactor (typically 100),
      not baked into node scale. If UnitScaleFactor is 1 and node scale is
      100, `apply_scale_options` was not `'FBX_SCALE_ALL'`.
    - Every Model's rotation should print as (0.0, 0.0, 0.0) (or very close
      to it -- float precision, not exactly 270). If it's ~270 degrees,
      `bake_space_transform` was not enabled (or was correctly left off for
      a rigged asset -- see SKILL.md's armature caveat).
    - Nodes flagged "[SCALE != 1]" / "[ROTATION != 0]" are the ones that
      will misbehave once something is parented under them or a Rigidbody
      is attached.

KNOWN LIMITATION: this only understands binary FBX 7.x (the format Blender's
exporter writes). ASCII FBX and pre-7.0 binary FBX are detected and rejected
with a clear message rather than mis-parsed -- see the magic-header and
version checks in `parse_fbx`. This is a verification aid, not a general FBX
library: it deliberately reads only GlobalSettings and Model transforms.
"""
from __future__ import annotations

import struct
import sys
import zlib
from dataclasses import dataclass, field

# The literal ASCII prefix every binary FBX file starts with. (Followed by
# two more bytes, \x1a\x00, which we don't need to check -- the text prefix
# alone is enough to distinguish binary FBX from ASCII FBX or any other
# file.)
MAGIC = b"Kaydara FBX Binary  \x00"

# Property type codes that carry a scalar value directly.
_SCALAR_UNPACK = {
    "Y": ("<h", 2),
    "C": ("<B", 1),
    "I": ("<i", 4),
    "F": ("<f", 4),
    "D": ("<d", 8),
    "L": ("<q", 8),
}

# Property type codes that carry an array: element format character for
# struct, used both to size and to unpack each element.
_ARRAY_ELEM_FMT = {"f": "f", "d": "d", "l": "q", "i": "i", "b": "B"}


class FbxParseError(Exception):
    """Raised when the input isn't a binary FBX 7.x file this can read."""


@dataclass
class Node:
    name: str
    properties: list
    children: list = field(default_factory=list)

    def child(self, name: str) -> "Node | None":
        return next((c for c in self.children if c.name == name), None)

    def children_named(self, name: str) -> list:
        return [c for c in self.children if c.name == name]


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise FbxParseError(f"unexpected end of file at offset {self.pos}")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return struct.unpack("<B", self.read(1))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]


def _read_property(r: _Reader):
    type_code = chr(r.read(1)[0])

    if type_code in _SCALAR_UNPACK:
        fmt, size = _SCALAR_UNPACK[type_code]
        return struct.unpack(fmt, r.read(size))[0]

    if type_code in _ARRAY_ELEM_FMT:
        array_len = r.u32()
        encoding = r.u32()
        compressed_len = r.u32()
        raw = r.read(compressed_len)
        if encoding:
            raw = zlib.decompress(raw)
        elem_fmt = "<" + _ARRAY_ELEM_FMT[type_code]
        elem_size = struct.calcsize(elem_fmt)
        values = [
            struct.unpack(elem_fmt, raw[i : i + elem_size])[0]
            for i in range(0, len(raw), elem_size)
        ]
        if len(values) != array_len:
            raise FbxParseError("array property length mismatch")
        return values

    if type_code in ("S", "R"):
        length = r.u32()
        data = r.read(length)
        return data.decode("utf-8", errors="replace") if type_code == "S" else data

    raise FbxParseError(f"unknown property type code {type_code!r} at offset {r.pos}")


def _read_node(r: _Reader, version: int) -> "Node | None":
    is_64bit = version >= 7500
    if is_64bit:
        end_offset, num_properties, property_list_len = r.u64(), r.u64(), r.u64()
    else:
        end_offset, num_properties, property_list_len = r.u32(), r.u32(), r.u32()

    name_len = r.u8()
    name = r.read(name_len).decode("utf-8", errors="replace")

    if end_offset == 0 and num_properties == 0 and property_list_len == 0 and name_len == 0:
        return None  # Null record: end of this nesting level's child list.

    prop_start = r.pos
    properties = [_read_property(r) for _ in range(num_properties)]
    # Trust end_offset over our own property-list bookkeeping if they
    # disagree -- keeps a misread property from cascading into garbage.
    r.pos = prop_start + property_list_len

    children = []
    while r.pos < end_offset:
        child = _read_node(r, version)
        if child is None:
            break
        children.append(child)
    r.pos = end_offset

    return Node(name=name, properties=properties, children=children)


def parse_fbx(data: bytes) -> list:
    if not data.startswith(MAGIC):
        raise FbxParseError(
            "not a binary FBX 7.x file (missing the 'Kaydara FBX Binary' magic "
            "header). This parser refuses ASCII FBX and non-FBX files rather "
            "than guessing -- re-export as binary FBX, or verify manually."
        )

    r = _Reader(data)
    # Two more bytes (\x1a\x00) follow the magic text before the version
    # field -- the magic constant above deliberately stops short of them so
    # it stays a clean printable-ish string for the detection check above.
    r.pos = len(MAGIC) + 2
    version = r.u32()
    if version < 7000:
        raise FbxParseError(
            f"unsupported FBX version {version}; this parser targets binary FBX 7.x"
        )

    nodes = []
    while True:
        node = _read_node(r, version)
        if node is None:
            break
        nodes.append(node)
    return nodes


def _properties70(node: Node) -> dict:
    """Map each Properties70 `P` entry's name -> its value properties.

    A `P` node's properties are [name, type, type2, flags, *values]; this
    drops the first four (metadata) and keeps only the values.
    """
    out = {}
    p70 = node.child("Properties70")
    if p70 is None:
        return out
    for p in p70.children_named("P"):
        if len(p.properties) < 4:
            continue
        out[p.properties[0]] = list(p.properties[4:])
    return out


def _vec3(values: list, default: tuple) -> tuple:
    if len(values) >= 3:
        return tuple(float(v) for v in values[:3])
    return default


def report(nodes: list) -> int:
    global_settings = next((n for n in nodes if n.name == "GlobalSettings"), None)
    if global_settings is None:
        print("WARNING: no GlobalSettings node found")
    else:
        gs = _properties70(global_settings)
        unit_scale = gs.get("UnitScaleFactor")
        up_axis = gs.get("UpAxis")
        print(f"GlobalSettings.UnitScaleFactor = {unit_scale[0] if unit_scale else 'MISSING'}")
        print(f"GlobalSettings.UpAxis = {up_axis[0] if up_axis else 'MISSING'}")

    objects = next((n for n in nodes if n.name == "Objects"), None)
    if objects is None:
        print("WARNING: no Objects node found")
        return 0

    models = objects.children_named("Model")
    if not models:
        print("No Model nodes found under Objects.")
        return 0

    print(f"\n{len(models)} Model node(s):")
    for m in models:
        model_name = m.properties[1] if len(m.properties) > 1 else m.name
        props = _properties70(m)
        translation = _vec3(props.get("Lcl Translation", []), default=(0.0, 0.0, 0.0))
        rotation = _vec3(props.get("Lcl Rotation", []), default=(0.0, 0.0, 0.0))
        scale = _vec3(props.get("Lcl Scaling", []), default=(1.0, 1.0, 1.0))

        flags = []
        if not all(abs(v - 1.0) < 1e-4 for v in scale):
            flags.append("SCALE != 1")
        if not all(abs(v) < 1e-4 for v in rotation):
            flags.append("ROTATION != 0")
        status = " ".join(flags) if flags else "OK"

        print(
            f"  {model_name!r}: translation={translation} rotation={rotation} "
            f"scale={scale}  [{status}]"
        )

    return 0


def main(argv: list) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <path-to.fbx>", file=sys.stderr)
        return 1

    path = argv[1]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        print(f"error: could not read {path!r}: {e}", file=sys.stderr)
        return 1

    try:
        nodes = parse_fbx(data)
    except FbxParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return report(nodes)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
