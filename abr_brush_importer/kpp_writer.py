"""
Krita Preset (.kpp) writer.

A .kpp file is a ZIP archive containing:
  - preset.xml   — brush settings in Krita's XML format
  - thumbnail.png — 64×64 preview image
  - <name>.gbr   — embedded brush tip (GIMP Brush v2)

The generated preset uses Krita's "paintbrush" (pixel brush) paint operation,
mapping ABR brush properties (spacing, opacity, flow, size, angle) directly
to Krita's preset parameters so dynamics are preserved — something GIMP
cannot do with ABR files.
"""

import io
import os
import struct
import zipfile
import zlib
from html import escape as _xml_escape
from typing import Optional

from .abr_parser import ABRParser, BrushTip, BrushDynamics


# ------------------------------------------------------------------ #
#  Public entry point                                                  #
# ------------------------------------------------------------------ #

def write_kpp(filepath: str, tip: BrushTip, invert: bool = False) -> None:
    """Write a Krita Preset (.kpp) file from a *BrushTip*.

    The preset embeds the brush tip as a GBR file inside the ZIP so the
    .kpp is entirely self-contained.

    Parameters
    ----------
    filepath : str
        Destination .kpp path (parent directories are created as needed).
    tip : BrushTip
        The parsed ABR brush tip.
    invert : bool
        When True, invert the grayscale brush tip before embedding.
    """
    name = tip.name or "Imported Brush"
    safe = _sanitize_filename(name)
    tip_filename = f"{safe}.gbr"

    # --- Brush tip pixel data (grayscale for GBR) ---
    gray = ABRParser.get_grayscale(tip) if tip.channels > 1 else tip.image_data
    if invert:
        gray = bytes(255 - b for b in gray)

    # --- Sizing and dynamics ---
    size = float(max(tip.width, tip.height, 1))
    spacing = max(0.01, tip.spacing / 100.0)
    dyn: Optional[BrushDynamics] = tip.dynamics
    opacity = (dyn.opacity / 100.0) if dyn else 1.0
    flow = (dyn.flow / 100.0) if dyn else 1.0
    angle = getattr(tip, 'angle', 0) if tip.brush_type == 1 else (dyn.angle if dyn else 0)

    # --- Extended dynamics (properties GIMP cannot preserve) ---
    # Hardness: use dynamics value if available, otherwise fall back to tip value.
    hardness = (dyn.hardness / 100.0) if dyn else (tip.hardness / 100.0)
    # Roundness/ratio: controls the Y/X aspect ratio of the brush tip ellipse.
    ratio = (dyn.roundness / 100.0) if dyn else (tip.roundness / 100.0)
    # Scatter: Photoshop stores scatter 0–1000 (%); map to 0–10 for Krita.
    scatter = (dyn.scatter / 1000.0 * 10.0) if dyn else 0.0
    scatter_count = max(1, dyn.count) if dyn else 1
    # Size and angle jitter for randomised stroke variation.
    size_jitter = (dyn.size_jitter / 100.0) if dyn else 0.0
    angle_jitter = (dyn.angle_jitter / 360.0) if dyn else 0.0
    # Stroke stabiliser.
    smoothing = dyn.smoothing if dyn else False

    # --- Build components ---
    gbr_bytes = _make_gbr_bytes(name, tip.width, tip.height, gray, tip.spacing)
    thumb_bytes = _make_thumbnail(tip, 64)
    preset_xml = _make_preset_xml(
        name=name,
        tip_filename=tip_filename,
        size=size,
        spacing=spacing,
        opacity=opacity,
        flow=flow,
        angle=angle,
        hardness=hardness,
        ratio=ratio,
        scatter=scatter,
        scatter_count=scatter_count,
        size_jitter=size_jitter,
        angle_jitter=angle_jitter,
        smoothing=smoothing,
    )

    # --- Pack into ZIP ---
    _ensure_dir(filepath)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr("preset.xml", preset_xml.encode("utf-8"))
        zf.writestr("thumbnail.png", thumb_bytes)
        zf.writestr(tip_filename, gbr_bytes)

    with open(filepath, 'wb') as fh:
        fh.write(buf.getvalue())


# ------------------------------------------------------------------ #
#  XML builder                                                         #
# ------------------------------------------------------------------ #

def _make_preset_xml(name: str, tip_filename: str, size: float,
                     spacing: float, opacity: float, flow: float,
                     angle: int = 0, hardness: float = 1.0,
                     ratio: float = 1.0, scatter: float = 0.0,
                     scatter_count: int = 1, size_jitter: float = 0.0,
                     angle_jitter: float = 0.0,
                     smoothing: bool = False) -> str:
    """Return the preset.xml string for a Krita pixel brush preset.

    All parameters beyond *angle* correspond to Photoshop brush dynamics that
    GIMP's ABR importer discards.  Preserving them here is the key advantage
    of this importer over a plain GBR export.

    Parameters
    ----------
    hardness : float
        Brush edge hardness (0–1).  Controls the soft-to-hard falloff.
    ratio : float
        Y/X aspect ratio of the brush ellipse (0–1).  1.0 = circular.
    scatter : float
        Random position offset amount for each dab (0–10).
    scatter_count : int
        Number of dabs placed per stamp when scatter is active.
    size_jitter : float
        Random size variation per dab (0–1).
    angle_jitter : float
        Random angle variation per dab (0–1, where 1 = full 360°).
    smoothing : bool
        Enable Krita's stroke stabiliser (AutoSmoothing).
    """

    # The brush_definition is an XML snippet embedded (escaped) inside the
    # outer XML.  It tells Krita which brush tip file to load and how.
    brush_def_inner = (
        f'<BrushPreset autoSpacingCoeff="1" angle="{angle}" '
        f'brush_style="predefined_brush" diameter="{int(size)}" '
        f'filename="{_xml_escape(tip_filename)}" '
        f'name="{_xml_escape(name)}" ratio="{ratio:.4f}" scale="1" '
        f'spacing="{spacing:.4f}" type="auto_brush">'
        f'</BrushPreset>'
    )
    brush_def_escaped = _xml_escape(brush_def_inner)

    smoothing_str = "true" if smoothing else "false"
    scatter_random_str = "true" if scatter > 0.0 else "false"

    xml = (
        '<!DOCTYPE KritaShapeLayer>\n'
        f'<params type="KisPaintOpPreset" name="{_xml_escape(name)}" version="5.0">\n'
        '  <param name="paintopid" type="string">paintbrush</param>\n'
        f'  <param name="name" type="string">{_xml_escape(name)}</param>\n'
        '  <param name="preset-icon" type="string">thumbnail.png</param>\n'
        '  <param name="paintop" type="paintop" id="paintbrush">\n'
        f'    <param name="brush_definition" type="string">{brush_def_escaped}</param>\n'
        f'    <param name="Spacing/isAuto" type="bool">false</param>\n'
        f'    <param name="Spacing/value" type="float">{spacing:.4f}</param>\n'
        f'    <param name="size" type="float">{size:.1f}</param>\n'
        f'    <param name="Opacity/value" type="float">{opacity:.4f}</param>\n'
        f'    <param name="flow" type="float">{flow:.4f}</param>\n'
        f'    <param name="hardness" type="float">{hardness:.4f}</param>\n'
        f'    <param name="AutoSmoothing/isChecked" type="bool">{smoothing_str}</param>\n'
        f'    <param name="Scatter/value" type="float">{scatter:.4f}</param>\n'
        f'    <param name="Scatter/useRandomOffset" type="bool">{scatter_random_str}</param>\n'
        f'    <param name="Scatter/count" type="int">{scatter_count}</param>\n'
        f'    <param name="SizeJitter/value" type="float">{size_jitter:.4f}</param>\n'
        f'    <param name="AngleJitter/value" type="float">{angle_jitter:.4f}</param>\n'
        '  </param>\n'
        '</params>\n'
    )
    return xml


# ------------------------------------------------------------------ #
#  GBR data builder (in-memory, no file I/O)                          #
# ------------------------------------------------------------------ #

def _make_gbr_bytes(name: str, width: int, height: int,
                    gray: bytes, spacing: int) -> bytes:
    """Return raw GBR v2 file bytes (for embedding inside the .kpp ZIP)."""
    name_bytes = name.encode('utf-8') + b'\x00'
    header_size = 28 + len(name_bytes)
    header = struct.pack(
        '>IIIII4sI',
        header_size,
        2,                                    # GBR version
        width,
        height,
        1,                                    # bytes per pixel (grayscale)
        b'GIMP',
        max(1, min(spacing, 1000)),
    )
    pixel_data = gray[:width * height]
    # Pad if necessary
    expected = width * height
    if len(pixel_data) < expected:
        pixel_data = pixel_data + b'\x00' * (expected - len(pixel_data))
    return header + name_bytes + pixel_data


# ------------------------------------------------------------------ #
#  Thumbnail builder (minimal PNG, no external deps)                  #
# ------------------------------------------------------------------ #

def _make_thumbnail(tip: BrushTip, size: int = 64) -> bytes:
    """Return a PNG-encoded thumbnail of *tip* (size×size, grayscale)."""
    # Nearest-neighbour scale of the grayscale tip to size×size
    src_w, src_h = tip.width, tip.height
    gray_src = ABRParser.get_grayscale(tip) if tip.channels > 1 else tip.image_data

    if src_w <= 0 or src_h <= 0 or not gray_src:
        # Blank white thumbnail
        raw = b'\xff' * (size * size)
    else:
        raw = bytearray(size * size)
        for dy in range(size):
            sy = min(int(dy * src_h / size), src_h - 1)
            for dx in range(size):
                sx = min(int(dx * src_w / size), src_w - 1)
                px = gray_src[sy * src_w + sx] if (sy * src_w + sx) < len(gray_src) else 0
                # Invert: brush data is 0=transparent, 255=opaque stroke
                # For thumbnail display, show stroke as dark on white.
                raw[dy * size + dx] = 255 - px

    return _encode_png_grayscale(bytes(raw), size, size)


def _encode_png_grayscale(data: bytes, width: int, height: int) -> bytes:
    """Encode raw 8-bit grayscale pixels to a PNG bytestring."""
    def _chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', crc)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: None
        rows.extend(data[y * width:(y + 1) * width])

    return (
        b'\x89PNG\r\n\x1a\n'
        + _chunk(b'IHDR', ihdr)
        + _chunk(b'IDAT', zlib.compress(bytes(rows), 6))
        + _chunk(b'IEND', b'')
    )


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:80] if safe else "brush"


def _ensure_dir(filepath: str) -> None:
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)
