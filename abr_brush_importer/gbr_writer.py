"""
Brush format writers for Krita-compatible brush tips.

Supports:
  .gbr  — GIMP Brush v2 (grayscale). Krita loads these natively as predefined brush tips.
  .png  — Standard PNG (grayscale). Also usable as brush tips in Krita.

The GBR format is preferred because it embeds the brush name and spacing directly.
"""

import struct
import os
import zlib


def write_gbr(filepath: str, name: str, width: int, height: int,
              image_data: bytes, spacing: int = 25) -> None:
    """Write a GIMP Brush v2 (.gbr) file.

    GBR v2 header layout (all fields big-endian):
      uint32  header_size   (28 + length of name including null terminator)
      uint32  version       (2)
      uint32  width
      uint32  height
      uint32  bytes_per_pixel  (1 = grayscale)
      char[4] magic         ("GIMP")
      uint32  spacing       (percentage, 1–1000)
      char[]  name          (null-terminated UTF-8)
    Followed by raw pixel data (width × height bytes, grayscale).
    """
    name_bytes = name.encode('utf-8') + b'\x00'
    header_size = 28 + len(name_bytes)

    header = struct.pack(
        '>IIIII4sI',
        header_size,
        2,                              # version
        width,
        height,
        1,                              # bytes per pixel (grayscale)
        b'GIMP',                        # magic
        max(1, min(spacing, 1000)),     # spacing
    )

    _ensure_dir(filepath)

    with open(filepath, 'wb') as f:
        f.write(header)
        f.write(name_bytes)
        f.write(image_data[:width * height])


def write_png(filepath: str, width: int, height: int,
              image_data: bytes) -> None:
    """Write a grayscale PNG file using only the standard library (no Pillow)."""
    _ensure_dir(filepath)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        body = chunk_type + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + body + struct.pack('>I', crc)

    signature = b'\x89PNG\r\n\x1a\n'

    # IHDR: width, height, bit depth 8, colour type 0 (grayscale)
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)

    # IDAT: each scanline is prefixed with a filter byte (0 = None)
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)                          # filter: None
        row_start = y * width
        raw_rows.extend(image_data[row_start:row_start + width])

    compressed = zlib.compress(bytes(raw_rows), 9)

    with open(filepath, 'wb') as f:
        f.write(signature)
        f.write(_chunk(b'IHDR', ihdr_data))
        f.write(_chunk(b'IDAT', compressed))
        f.write(_chunk(b'IEND', b''))


def _ensure_dir(filepath: str) -> None:
    """Create parent directories for *filepath* if they don't exist."""
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)
