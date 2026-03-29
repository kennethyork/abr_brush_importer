"""
Brush format writers for Krita-compatible brush tips.

Supports:
  .gbr  — GIMP Brush v2 (grayscale or RGBA). Krita loads these natively.
  .png  — Standard PNG (grayscale or RGBA). Also usable as brush tips.

The GBR format is preferred because it embeds the brush name and spacing directly.
"""

import struct
import os
import zlib


def write_gbr(filepath: str, name: str, width: int, height: int,
              image_data: bytes, spacing: int = 25,
              channels: int = 1) -> None:
    """Write a GIMP Brush v2 (.gbr) file.

    channels: 1 = grayscale, 4 = RGBA.
    GBR v2 header layout (all fields big-endian):
      uint32  header_size   (28 + length of name including null terminator)
      uint32  version       (2)
      uint32  width
      uint32  height
      uint32  bytes_per_pixel  (1 = grayscale, 4 = RGBA)
      char[4] magic         ("GIMP")
      uint32  spacing       (percentage, 1–1000)
      char[]  name          (null-terminated UTF-8)
    Followed by raw pixel data.
    """
    bpp = channels if channels in (1, 3, 4) else 1
    name_bytes = name.encode('utf-8') + b'\x00'
    header_size = 28 + len(name_bytes)

    header = struct.pack(
        '>IIIII4sI',
        header_size,
        2,                              # version
        width,
        height,
        bpp,                            # bytes per pixel
        b'GIMP',                        # magic
        max(1, min(spacing, 1000)),     # spacing
    )

    _ensure_dir(filepath)

    with open(filepath, 'wb') as f:
        f.write(header)
        f.write(name_bytes)
        f.write(image_data[:width * height * bpp])


def write_png(filepath: str, width: int, height: int,
              image_data: bytes, channels: int = 1) -> None:
    """Write a PNG file (grayscale or RGBA) using only the standard library."""
    _ensure_dir(filepath)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        body = chunk_type + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + body + struct.pack('>I', crc)

    signature = b'\x89PNG\r\n\x1a\n'

    # colour type: 0 = grayscale, 2 = RGB, 6 = RGBA
    if channels == 4:
        colour_type = 6
    elif channels == 3:
        colour_type = 2
    else:
        colour_type = 0

    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, colour_type, 0, 0, 0)

    row_bytes = width * channels
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)                          # filter: None
        row_start = y * row_bytes
        raw_rows.extend(image_data[row_start:row_start + row_bytes])

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
