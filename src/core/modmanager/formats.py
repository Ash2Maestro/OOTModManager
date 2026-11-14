"""Strict IPS/IPS32 parsing and NSO normalization. No game files required to import."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct


class FormatError(ValueError):
    pass


def align(value: int, size: int = 0x1000) -> int:
    return (value + size - 1) & ~(size - 1)


@dataclass(frozen=True)
class Record:
    offset: int  # module-relative virtual address, excluding synthetic NSO header
    data: bytes


def parse_ips(raw: bytes, header_bias: int = 0x100) -> list[Record]:
    """Switch patches address a synthetic header + uncompressed virtual image.

    File truncation extensions and header edits are deliberately unsupported.
    """
    if raw.startswith(b"IPS32"):
        width, end = 4, b"EEOF"
    elif raw.startswith(b"PATCH"):
        width, end = 3, b"EOF"
    else:
        raise FormatError("Signature IPS/IPS32 inconnue")
    pos, records = 5, []

    def take(count: int) -> bytes:
        nonlocal pos
        if pos + count > len(raw):
            raise FormatError("Patch IPS tronque")
        result = raw[pos:pos + count]
        pos += count
        return result

    while True:
        address = take(width)
        if address == end:
            if pos != len(raw):
                raise FormatError("Extension de troncature ou octets apres la fin IPS non pris en charge")
            return records
        offset = int.from_bytes(address, "big") - header_bias
        size = int.from_bytes(take(2), "big")
        if size:
            data = take(size)
        else:
            count = int.from_bytes(take(2), "big")
            value = take(1)
            if not count:
                raise FormatError("Enregistrement RLE vide")
            data = value * count
        if offset < 0:
            raise FormatError("Les modifications de l'en-tete NSO par IPS sont refusees")
        stop = offset + len(data)
        if any(offset < r.offset + len(r.data) and r.offset < stop for r in records):
            raise FormatError("Enregistrements IPS superposes")
        records.append(Record(offset, data))


@dataclass
class Segment:
    memory: int
    data: bytes


class Nso:
    MAX_IMAGE = 512 * 1024 * 1024

    def __init__(self, raw: bytes):
        if len(raw) < 0x100 or raw[:4] != b"NSO0":
            raise FormatError("Module NSO0 invalide ou tronque")
        self.header = bytearray(raw[:0x100])
        self.flags = struct.unpack_from("<I", raw, 0xC)[0]
        self.bss = struct.unpack_from("<I", raw, 0x3C)[0]
        self.build_id = raw[0x40:0x60].rstrip(b"\0").hex()
        descriptors = [struct.unpack_from("<III", raw, 0x10 + 16 * i) for i in range(3)]
        if min(x[0] for x in descriptors) < 0x100:
            raise FormatError("Segment NSO dans l'en-tete")
        self.prefix = raw[0x100:min(x[0] for x in descriptors)]
        self.segments = []
        stored_ranges = []
        for i, (file_offset, memory, size) in enumerate(descriptors):
            stored = struct.unpack_from("<I", raw, 0x60 + 4 * i)[0]
            if memory + size > self.MAX_IMAGE or file_offset + stored > len(raw):
                raise FormatError("Segment NSO hors limites")
            if stored and any(file_offset < hi and lo < file_offset + stored for lo, hi in stored_ranges):
                raise FormatError("Segments NSO superposes sur disque")
            stored_ranges.append((file_offset, file_offset + stored))
            data = raw[file_offset:file_offset + stored]
            if self.flags & (1 << i):
                if self.flags & 0x80:
                    import zbic
                    # PyPI zbic accepts one frame argument (Longshot has a separate
                    # nx2/zbic.py adapter with a different two-argument API).
                    data = zbic.decompress(data)
                else:
                    import lz4.block
                    data = lz4.block.decompress(data, uncompressed_size=size)
            if len(data) != size:
                raise FormatError("Taille de segment NSO incorrecte")
            if self.flags & (8 << i):
                if hashlib.sha256(data).digest() != raw[0xA0 + 32 * i:0xC0 + 32 * i]:
                    raise FormatError("Empreinte SHA256 de segment NSO incorrecte")
            self.segments.append(Segment(memory, data))
        text, ro, data = self.segments
        if text.memory != 0 or text.memory + len(text.data) > ro.memory:
            raise FormatError("Disposition texte/rodata NSO non prise en charge")
        if ro.memory + len(ro.data) > data.memory:
            raise FormatError("Segments rodata/data superposes")
        if self.end > self.MAX_IMAGE:
            raise FormatError("Image NSO trop grande")

    @property
    def end(self) -> int:
        data = self.segments[2]
        return data.memory + len(data.data) + self.bss

    @property
    def mapped_size(self) -> int:
        return align(self.end)

    def apply(self, records: list[Record]) -> list[dict]:
        """Materialize BSS initialization in .data, keeping total VM size fixed.

        Code written into the text's executable page padding extends .text without
        moving rodata, data, or later modules. IPS offsets never index compressed files.
        """
        original_end = self.end
        text, ro, data = self.segments
        text_end = len(text.data)
        data_end = data.memory + len(data.data)
        changes = []
        # Validate every record before applying any of them.
        for record in records:
            lo, hi = record.offset, record.offset + len(record.data)
            if 0 <= lo and hi <= min(align(text_end), ro.memory):
                index, kind = 0, "text" if hi <= text_end else "text-padding"
            elif ro.memory <= lo and hi <= ro.memory + len(ro.data):
                index, kind = 1, "rodata"
            elif data.memory <= lo and hi <= original_end:
                index, kind = 2, "data" if hi <= data_end else "bss-initialization"
            else:
                raise FormatError("IPS hors segment/padding pris en charge : %#x..%#x" % (lo, hi))
            changes.append({"offset": lo, "size": len(record.data), "segment": index, "kind": kind})
        for record, change in zip(records, changes):
            segment = self.segments[change["segment"]]
            body = bytearray(segment.data)
            relative = record.offset - segment.memory
            needed = relative + len(record.data)
            if change["segment"] == 0:
                needed = align(needed, 4)
            if needed > len(body):
                body.extend(bytes(needed - len(body)))
            body[relative:relative + len(record.data)] = record.data
            segment.data = bytes(body)
        self.bss = original_end - (data.memory + len(data.data))
        if self.end != original_end:
            raise FormatError("Le patch a change la taille virtuelle du module")
        return changes

    def encode(self) -> bytes:
        header = bytearray(self.header)
        body = bytearray(self.prefix)
        # Uncompressed segments with regenerated hashes, and original build identity.
        struct.pack_into("<I", header, 0xC, (self.flags & ~(0x80 | 7)) | 0x38)
        struct.pack_into("<I", header, 0x3C, self.bss)
        for i, segment in enumerate(self.segments):
            body.extend(bytes((-(0x100 + len(body))) % 16))
            struct.pack_into("<III", header, 0x10 + 16 * i,
                             0x100 + len(body), segment.memory, len(segment.data))
            struct.pack_into("<I", header, 0x60 + 4 * i, len(segment.data))
            header[0xA0 + 32 * i:0xC0 + 32 * i] = hashlib.sha256(segment.data).digest()
            body.extend(segment.data)
        return bytes(header + body)


MODULES = ["rtld", "main"] + ["subsdk%d" % i for i in range(10)] + ["sdk"]


def module_layout(modules: dict[str, Nso]) -> list[dict]:
    base, result = 0x80000000, []
    for name in MODULES:
        if name not in modules:
            continue
        module = modules[name]
        text = module.segments[0]
        result.append({"name": name, "base": base, "size": module.mapped_size,
                       "build_id": module.build_id, "text_start": base + text.memory,
                       "text_end": base + text.memory + len(text.data)})
        base += module.mapped_size
    return result


def branch_target(word: int, pc: int) -> int | None:
    """Direct AArch64 B/BL, B.cond, CBZ/CBNZ, TBZ/TBNZ only."""
    if word & 0x7C000000 == 0x14000000:
        immediate, bits = word & 0x3FFFFFF, 26
    elif word & 0xFF000010 == 0x54000000 or word & 0x7E000000 == 0x34000000:
        immediate, bits = (word >> 5) & 0x7FFFF, 19
    elif word & 0x7E000000 == 0x36000000:
        immediate, bits = (word >> 5) & 0x3FFF, 14
    else:
        return None
    signed = immediate - (1 << bits) if immediate & (1 << (bits - 1)) else immediate
    return pc + signed * 4


def audit_changed_branches(name: str, before: bytes, after: bytes, layout: list[dict]) -> list[dict]:
    """Check changed instructions in replaced original modules, not embedded data in helpers."""
    base = next(m["base"] for m in layout if m["name"] == name)
    found = []
    for offset in changed_words(before, after):
        word = struct.unpack_from("<I", after, offset)[0]
        pc = base + offset
        target = branch_target(word, pc)
        if target is None:
            continue
        owner = next((m for m in layout if m["text_start"] <= target < m["text_end"]), None)
        if owner is None:
            raise FormatError("Branchement modifie hors code : %s+%#x -> %#x" % (name, offset, target))
        found.append({"module": name, "offset": offset, "target": target, "target_module": owner["name"]})
    return found


def changed_words(before: bytes, after: bytes):
    limit = min(len(before), len(after)) & ~3
    for start in range(0, limit, 4096):
        stop = min(start + 4096, limit)
        if before[start:stop] == after[start:stop]:
            continue
        for offset in range(start, stop, 4):
            if before[offset:offset + 4] != after[offset:offset + 4]:
                yield offset


def changed_ranges(before: bytes, after: bytes) -> list[list[int]]:
    ranges = []
    for offset in changed_words(before, after):
        if ranges and ranges[-1][1] == offset:
            ranges[-1][1] = offset + 4
        else:
            ranges.append([offset, offset + 4])
    return ranges
