"""Content fingerprints for prepared guest code and installed images."""
import hashlib
from pathlib import Path



def image_digest(path: Path, ignored_offset=None):
    h = hashlib.sha256()
    position = 0
    with path.open("rb") as stream:
        while raw := stream.read(8 << 20):
            if ignored_offset is not None:
                start = max(position, ignored_offset)
                end = min(position + len(raw), ignored_offset + 4)
                if start < end:
                    data = bytearray(raw)
                    data[start - position:end - position] = bytes(end - start)
                    raw = data
            h.update(raw)
            position += len(raw)
    return h.hexdigest()
