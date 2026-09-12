from __future__ import annotations

from typing import BinaryIO


DEFAULT_CHUNK_BYTES = 64 * 1024


def read_limited(handle: BinaryIO, limit: int, *, chunk_size: int = DEFAULT_CHUNK_BYTES) -> bytes:
    payload = bytearray()
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
        if len(payload) > limit:
            raise ValueError(f"Response is larger than {limit} bytes.")
