"""
Krita Preset (.kpp) writer.

A Krita 5.x .kpp file is a **PNG image** (200×200 thumbnail) with a
``zTXt`` chunk (keyword ``"preset"``) containing zlib-compressed XML
preset settings.  The brush tip itself lives as a separate ``.gbr``
file in ``brushes/`` and is referenced by filename inside the XML.

The generated preset uses Krita's ``paintbrush`` (pixel brush) engine,
mapping ABR brush properties (spacing, opacity, flow, size, angle)
directly to Krita's preset parameters so dynamics are preserved —
something GIMP cannot do with ABR files.
"""

import os
import struct
import zlib
from typing import List, Optional, Tuple

from .abr_parser import ABRParser, BrushTip, BrushDynamics


# ------------------------------------------------------------------ #
#  Public entry point                                                  #
# ------------------------------------------------------------------ #

def write_kpp(filepath: str, tip: BrushTip, invert: bool = False,
              use_pressure: bool = True,
              preset_name: Optional[str] = None) -> None:
    """Write a Krita Preset (.kpp) file from a *BrushTip*.

    The .kpp is a PNG thumbnail with embedded preset XML.  The brush
    tip ``.gbr`` is referenced by filename (it must exist separately
    in the ``brushes/`` resource directory).

    Parameters
    ----------
    filepath : str
        Destination .kpp path (parent directories are created as needed).
    tip : BrushTip
        The parsed ABR brush tip.
    invert : bool
        When True, invert the grayscale brush tip before embedding.
    use_pressure : bool
        When True (default), enable pressure sensitivity for brush size.
    preset_name : str, optional
        Override name for the preset.  When ``None``, uses ``tip.name``.
    """
    name = preset_name or tip.name or "Imported Brush"
    safe = _sanitize_filename(name)
    tip_filename = f"{safe}.gbr"

    # --- Sizing and dynamics ---
    size = float(max(tip.width, tip.height, 1))
    spacing = max(0.01, tip.spacing / 100.0)
    dyn: Optional[BrushDynamics] = tip.dynamics
    opacity = (dyn.opacity / 100.0) if dyn else 1.0
    flow = (dyn.flow / 100.0) if dyn else 1.0
    angle = getattr(tip, 'angle', 0) if tip.brush_type == 1 else (dyn.angle if dyn else 0)

    ratio = (dyn.roundness / 100.0) if dyn else (tip.roundness / 100.0)

    # --- Pressure curves ---
    if dyn and dyn.size_pressure_curve:
        size_curve: Optional[List[Tuple[float, float]]] = dyn.size_pressure_curve
    elif use_pressure:
        size_curve = [(0.0, 0.0), (1.0, 1.0)]
    else:
        size_curve = None

    opacity_curve: Optional[List[Tuple[float, float]]] = (
        dyn.opacity_pressure_curve if (dyn and dyn.opacity_pressure_curve) else None
    )
    flow_curve: Optional[List[Tuple[float, float]]] = (
        dyn.flow_pressure_curve if (dyn and dyn.flow_pressure_curve) else None
    )

    # --- Build XML ---
    preset_xml = _make_preset_xml(
        name=name,
        tip_filename=tip_filename,
        size=size,
        spacing=spacing,
        opacity=opacity,
        flow=flow,
        angle=angle,
        ratio=ratio,
        use_pressure=use_pressure,
        size_curve=size_curve,
        opacity_curve=opacity_curve,
        flow_curve=flow_curve,
    )

    # --- Build PNG with embedded zTXt preset ---
    png_bytes = _make_kpp_png(tip, invert, preset_xml)

    _ensure_dir(filepath)
    with open(filepath, 'wb') as fh:
        fh.write(png_bytes)


# ------------------------------------------------------------------ #
#  PNG builder — 200×200 RGBA thumbnail with zTXt preset chunk        #
# ------------------------------------------------------------------ #

_THUMB_SIZE = 200


def _make_kpp_png(tip: BrushTip, invert: bool, preset_xml: str) -> bytes:
    """Return complete .kpp file bytes (PNG with embedded preset XML)."""
    rgba = _make_thumbnail_rgba(tip, _THUMB_SIZE, invert)
    compressed_xml = zlib.compress(preset_xml.encode('utf-8'), 6)

    # Build PNG manually: signature + IHDR + zTXt + IDAT + IEND
    ihdr_data = struct.pack('>IIBBBBB', _THUMB_SIZE, _THUMB_SIZE,
                            8, 6, 0, 0, 0)  # 8-bit RGBA
    # zTXt chunk: keyword(NUL)compression_method(byte)compressed_data
    ztxt_payload = b'preset\x00\x00' + compressed_xml

    # IDAT: raw RGBA rows with filter byte 0 per row
    raw_rows = bytearray()
    stride = _THUMB_SIZE * 4
    for y in range(_THUMB_SIZE):
        raw_rows.append(0)  # filter: None
        raw_rows.extend(rgba[y * stride:(y + 1) * stride])
    idat_data = zlib.compress(bytes(raw_rows), 6)

    # pHYs: 3780 pixels/meter ≈ 96 DPI (matches Krita's preset files)
    phys_data = struct.pack('>IIB', 3780, 3780, 1)

    # tEXt version chunk — Krita requires this to accept the preset
    text_version = b'version\x002.2'

    return (
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', ihdr_data)
        + _png_chunk(b'pHYs', phys_data)
        + _png_chunk(b'zTXt', ztxt_payload)
        + _png_chunk(b'tEXt', text_version)
        + _png_chunk(b'IDAT', idat_data)
        + _png_chunk(b'IEND', b'')
    )


def _png_chunk(tag: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(tag + body) & 0xFFFFFFFF
    return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', crc)


def _make_thumbnail_rgba(tip: BrushTip, size: int, invert: bool) -> bytes:
    """Return raw RGBA pixel data (size×size×4 bytes) for the thumbnail."""
    src_w, src_h = tip.width, tip.height
    gray_src = ABRParser.get_grayscale(tip) if tip.channels > 1 else tip.image_data

    if src_w <= 0 or src_h <= 0 or not gray_src:
        return b'\xff\xff\xff\xff' * (size * size)

    buf = bytearray(size * size * 4)
    for dy in range(size):
        sy = min(int(dy * src_h / size), src_h - 1)
        for dx in range(size):
            sx = min(int(dx * src_w / size), src_w - 1)
            idx = sy * src_w + sx
            alpha = gray_src[idx] if idx < len(gray_src) else 0
            if invert:
                alpha = 255 - alpha
            # Brush tips: 0 = transparent, 255 = opaque stroke.
            # Thumbnail: dark stroke on transparent background.
            off = (dy * size + dx) * 4
            buf[off] = 0       # R
            buf[off + 1] = 0   # G
            buf[off + 2] = 0   # B
            buf[off + 3] = alpha  # A
    return bytes(buf)


# ------------------------------------------------------------------ #
#  XML builder — Krita 5.x <Preset> format                           #
# ------------------------------------------------------------------ #

def _make_preset_xml(name: str, tip_filename: str, size: float,
                     spacing: float, opacity: float, flow: float,
                     angle: int = 0, ratio: float = 1.0,
                     use_pressure: bool = True,
                     size_curve: Optional[List[Tuple[float, float]]] = None,
                     opacity_curve: Optional[List[Tuple[float, float]]] = None,
                     flow_curve: Optional[List[Tuple[float, float]]] = None,
                     ) -> str:
    """Build Krita 5.x preset XML in the ``<Preset>`` format."""

    # Brush definition — reference the .gbr file via gbr_brush type
    brush_def = (
        f'<Brush type="gbr_brush" BrushVersion="2"'
        f' filename="{_xml_esc(tip_filename)}"'
        f' spacing="{spacing:.4f}"'
        f' useAutoSpacing="0" autoSpacingCoeff="1"'
        f' angle="{angle}" scale="1"'
        f' ColorAsMask="1" AdjustmentMidPoint="127"'
        f' BrightnessAdjustment="0" ContrastAdjustment="0"'
        f' preserveLightness="0"/>'
    )

    # Sensor helper
    def _sensor(curve_pts=None):
        if curve_pts:
            c = ";".join(f"{x},{y}" for x, y in curve_pts) + ";"
            return f'<!DOCTYPE params> <params id="pressure"> <curve>{c}</curve> </params> '
        return '<!DOCTYPE params> <params id="pressure"/> '

    default_sensor = _sensor()
    default_curve_sensor = _sensor([(0, 0), (1, 1)])

    # Size sensor
    if size_curve:
        size_sensor = _sensor(size_curve)
        pressure_size = "true"
        size_use_curve = "true"
    else:
        size_sensor = default_curve_sensor
        pressure_size = "false"
        size_use_curve = "false"

    # Opacity sensor
    if opacity_curve:
        opacity_sensor = _sensor(opacity_curve)
        pressure_opacity = "true"
        opacity_use_curve = "true"
    else:
        opacity_sensor = default_curve_sensor
        pressure_opacity = "false"
        opacity_use_curve = "false"

    # Flow sensor
    if flow_curve:
        flow_sensor = _sensor(flow_curve)
        pressure_flow = "true"
        flow_use_curve = "true"
    else:
        flow_sensor = default_sensor
        flow_use_curve = "false"
        pressure_flow = "false"

    esc_name = _xml_esc(name)

    # Build the full XML with all standard params Krita expects.
    # Every value is wrapped in CDATA inside a <param type="string"> element.
    params = [
        ("ColorSource/Type", "plain"),
        ("CompositeOp", "normal"),
        ("EraserMode", "false"),
        ("FlowSensor", flow_sensor),
        ("FlowUseCurve", flow_use_curve),
        ("FlowUseSameCurve", "true"),
        ("FlowValue", f"{flow:.4f}"),
        ("FlowcurveMode", "0"),
        ("HorizontalMirrorEnabled", "false"),
        ("KisPrecisionOption/AutoPrecisionEnabled", "true"),
        ("KisPrecisionOption/DeltaValue", "15"),
        ("KisPrecisionOption/SizeToStartFrom", "10"),
        ("KisPrecisionOption/precisionLevel", "5"),
        ("MaskingBrush/Enabled", "false"),
        ("MirrorSensor", default_sensor),
        ("MirrorUseCurve", "true"),
        ("MirrorUseSameCurve", "true"),
        ("MirrorValue", "1"),
        ("MirrorcurveMode", "0"),
        ("OpacitySensor", opacity_sensor),
        ("OpacityUseCurve", opacity_use_curve),
        ("OpacityUseSameCurve", "true"),
        ("OpacityValue", f"{opacity:.4f}"),
        ("OpacitycurveMode", "0"),
        ("OpacityVersion", "2"),
        ("PaintOpAction", "2"),
        ("PaintOpSettings/ignoreSpacing", "false"),
        ("PaintOpSettings/isAirbrushing", "false"),
        ("PaintOpSettings/rate", "20"),
        ("PaintOpSettings/updateSpacingBetweenDabs", "false"),
        ("PressureDarken", "false"),
        ("PressureMirror", "false"),
        ("PressureMix", "false"),
        ("PressureRate", "false"),
        ("PressureRatio", "false"),
        ("PressureRotation", "false"),
        ("PressureScatter", "false"),
        ("PressureSharpness", "false"),
        ("PressureSize", pressure_size),
        ("PressureSoftness", "false"),
        ("PressureSpacing", "false"),
        ("PressureTexture/Strength/", "false"),
        ("Pressureh", "false"),
        ("Pressures", "false"),
        ("Pressurev", "false"),
        ("RatioSensor", default_sensor),
        ("RatioUseCurve", "true"),
        ("RatioUseSameCurve", "true"),
        ("RatioValue", f"{ratio:.4f}"),
        ("RatiocurveMode", "0"),
        ("RotationSensor", default_sensor),
        ("RotationUseCurve", "true"),
        ("RotationUseSameCurve", "true"),
        ("RotationValue", "1"),
        ("RotationcurveMode", "0"),
        ("ScatterSensor", default_sensor),
        ("ScatterUseCurve", "true"),
        ("ScatterUseSameCurve", "true"),
        ("ScatterValue", "5"),
        ("ScattercurveMode", "0"),
        ("Scattering/AxisX", "true"),
        ("Scattering/AxisY", "true"),
        ("Sharpness/threshold", "4"),
        ("SharpnessSensor", default_sensor),
        ("SharpnessUseCurve", "true"),
        ("SharpnessUseSameCurve", "true"),
        ("SharpnessValue", "1"),
        ("SharpnesscurveMode", "0"),
        ("SizeSensor", size_sensor),
        ("SizeUseCurve", size_use_curve),
        ("SizeUseSameCurve", "true"),
        ("SizeValue", "1"),
        ("SizecurveMode", "0"),
        ("SoftnessSensor", default_sensor),
        ("SoftnessUseCurve", "true"),
        ("SoftnessUseSameCurve", "true"),
        ("SoftnessValue", "1"),
        ("SoftnesscurveMode", "0"),
        ("Spacing/Isotropic", "false"),
        ("SpacingSensor", default_sensor),
        ("SpacingUseCurve", "true"),
        ("SpacingUseSameCurve", "true"),
        ("SpacingValue", "1"),
        ("SpacingcurveMode", "0"),
        ("Texture/Pattern/Enabled", "false"),
        ("VerticalMirrorEnabled", "false"),
        ("brush_definition", brush_def + " "),
        ("paintop", "paintbrush"),
        ("requiredBrushFile", tip_filename),
        ("requiredBrushFilesList", tip_filename),
    ]

    parts = [f'<Preset name="{esc_name}" paintopid="paintbrush">']
    for pname, pval in params:
        parts.append(
            f' <param name="{pname}" type="string">'
            f'<![CDATA[{pval}]]></param>'
        )
    parts.append(' </Preset>')
    return " ".join(parts)


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _xml_esc(text: str) -> str:
    """Escape text for use in XML attribute values."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))


def _sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:80] if safe else "brush"


def _ensure_dir(filepath: str) -> None:
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)
