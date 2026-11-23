"""
app/wifi/imagesize.py
---------------------
Type and pixel size of an uploaded floor plan, read from the file's own
header. Only PNG and JPEG are accepted, decided by the leading bytes and never
by a file name or content type the client supplied. Nothing is decoded, so no
imaging library is needed.
"""
from __future__ import annotations

from typing import Optional

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8"

# JPEG start-of-frame markers carry the dimensions. 0xC4, 0xC8 and 0xCC share
# the range but are not frames (huffman tables, reserved, arithmetic tables).
_JPEG_SOF = {m for m in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}


def image_info(data: bytes) -> Optional[tuple[str, int, int]]:
    """(extension, width, height) for a PNG or JPEG, or None for anything else
    or a file whose header cannot be read."""
    if data[:8] == _PNG_SIGNATURE:
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return ("png", w, h) if w > 0 and h > 0 else None

    if data[:2] == _JPEG_SOI:
        i = 2
        n = len(data)
        while i + 4 <= n:
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:          # fill byte before a marker
                i += 1
                continue
            if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:   # no length field
                i += 2
                continue
            if marker == 0xD9:          # end of image, no frame seen
                return None
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if length < 2:
                return None
            if marker in _JPEG_SOF:
                if i + 9 > n:
                    return None
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return ("jpg", w, h) if w > 0 and h > 0 else None
            i += 2 + length
        return None

    return None
