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

    if dyn and dyn.opacity_pressure_curve:
        opacity_curve: Optional[List[Tuple[float, float]]] = dyn.opacity_pressure_curve
    elif use_pressure:
        opacity_curve = [(0.0, 0.0), (1.0, 1.0)]
    else:
        opacity_curve = None

    flow_curve: Optional[List[Tuple[float, float]]] = (
        dyn.flow_pressure_curve if (dyn and dyn.flow_pressure_curve) else None
    )

    # --- Scatter ---
    scatter_val = 0.0
    scatter_count = 1
    scatter_both = False
    if dyn and dyn.scatter > 0:
        scatter_val = dyn.scatter / 100.0  # PS 0-1000% → Krita 0-10
        scatter_count = dyn.count
        scatter_both = dyn.scatter_both_axes

    # --- Jitters (size / angle / roundness) ---
    size_jitter = (dyn.size_jitter / 100.0) if dyn else 0.0
    angle_jitter = (dyn.angle_jitter / 360.0) if dyn else 0.0
    roundness_jitter = (dyn.roundness_jitter / 100.0) if dyn else 0.0

    # --- Flip / Mirror ---
    flip_x = dyn.flip_x if dyn else False
    flip_y = dyn.flip_y if dyn else False

    # --- Airbrush ---
    airbrush = dyn.airbrush if dyn else False

    # --- Smoothing ---
    smoothing = dyn.smoothing if dyn else False

    # --- Color dynamics (hue / saturation / value jitter) ---
    hue_jitter = (dyn.hue_jitter / 100.0) if dyn else 0.0
    sat_jitter = (dyn.saturation_jitter / 100.0) if dyn else 0.0
    val_jitter = (dyn.brightness_jitter / 100.0) if dyn else 0.0

    # --- Texture ---
    texture_enabled = dyn.texture_enabled if dyn else False
    texture_pattern = dyn.texture_pattern_name if dyn else ""
    texture_scale = (dyn.texture_scale / 100.0) if dyn else 1.0
    texture_depth = (dyn.texture_depth / 100.0) if dyn else 1.0

    # --- Masking brush (dual brush) ---
    masking_enabled = dyn.dual_brush_enabled if dyn else False

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
        scatter_val=scatter_val,
        scatter_count=scatter_count,
        scatter_both=scatter_both,
        size_jitter=size_jitter,
        angle_jitter=angle_jitter,
        roundness_jitter=roundness_jitter,
        flip_x=flip_x,
        flip_y=flip_y,
        airbrush=airbrush,
        smoothing=smoothing,
        hue_jitter=hue_jitter,
        sat_jitter=sat_jitter,
        val_jitter=val_jitter,
        texture_enabled=texture_enabled,
        texture_pattern=texture_pattern,
        texture_scale=texture_scale,
        texture_depth=texture_depth,
        masking_enabled=masking_enabled,
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
                     scatter_val: float = 0.0,
                     scatter_count: int = 1,
                     scatter_both: bool = False,
                     size_jitter: float = 0.0,
                     angle_jitter: float = 0.0,
                     roundness_jitter: float = 0.0,
                     flip_x: bool = False,
                     flip_y: bool = False,
                     airbrush: bool = False,
                     smoothing: bool = False,
                     hue_jitter: float = 0.0,
                     sat_jitter: float = 0.0,
                     val_jitter: float = 0.0,
                     texture_enabled: bool = False,
                     texture_pattern: str = "",
                     texture_scale: float = 1.0,
                     texture_depth: float = 1.0,
                     masking_enabled: bool = False,
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

    # Sensor helper — format matches Krita's native output
    def _sensor(sensor_id="pressure", curve_pts=None):
        if curve_pts:
            c = ";".join(f"{x},{y}" for x, y in curve_pts) + ";"
            return (f'<!DOCTYPE params> <params id="{sensor_id}">'
                    f' <curve>{c}</curve> </params> ')
        return f'<!DOCTYPE params> <params id="{sensor_id}"/> '

    def _multi_sensor(*sensors):
        """Combine multiple sensor XML strings into one value."""
        return " ".join(s.strip() for s in sensors) + " "

    linear_curve = [(0, 0), (1, 1)]
    default_sensor = _sensor("pressure", linear_curve)

    # ---- Size sensor (pressure + optional random jitter) ----
    if size_curve:
        size_pressure = _sensor("pressure", size_curve)
        pressure_size = "true"
        size_use_curve = "true"
    else:
        size_pressure = default_sensor
        pressure_size = "false"
        size_use_curve = "false"

    if size_jitter > 0:
        size_sensor = _multi_sensor(size_pressure, _sensor("random"))
        size_use_curve = "true"
    else:
        size_sensor = size_pressure

    # ---- Opacity sensor ----
    if opacity_curve:
        opacity_sensor = _sensor("pressure", opacity_curve)
        pressure_opacity = "true"
        opacity_use_curve = "true"
    else:
        opacity_sensor = default_sensor
        pressure_opacity = "false"
        opacity_use_curve = "false"

    # ---- Flow sensor ----
    if flow_curve:
        flow_sensor = _sensor("pressure", flow_curve)
        flow_use_curve = "true"
    else:
        flow_sensor = default_sensor
        flow_use_curve = "false"

    # ---- Rotation sensor (angle jitter → random) ----
    if angle_jitter > 0:
        rotation_sensor = _sensor("random")
        rotation_use_curve = "true"
    else:
        rotation_sensor = _sensor("pressure")
        rotation_use_curve = "true"

    # ---- Ratio sensor (roundness jitter → random) ----
    if roundness_jitter > 0:
        ratio_sensor = _multi_sensor(_sensor("pressure"), _sensor("random"))
        ratio_use_curve = "true"
    else:
        ratio_sensor = _sensor("pressure")
        ratio_use_curve = "true"

    # ---- Scatter sensor ----
    has_scatter = scatter_val > 0
    if has_scatter:
        scatter_sensor = default_sensor
        scatter_use_curve = "true"
    else:
        scatter_sensor = default_sensor
        scatter_use_curve = "false"

    # ---- Mirror / Flip (per-dab random flip) ----
    has_flip = flip_x or flip_y
    if has_flip:
        mirror_sensor = _sensor("random")
    else:
        mirror_sensor = _sensor("pressure")

    # ---- Color dynamics (h/s/v jitter → random sensors) ----
    h_sensor = _sensor("random") if hue_jitter > 0 else default_sensor
    s_sensor = _sensor("random") if sat_jitter > 0 else default_sensor
    v_sensor = _sensor("random") if val_jitter > 0 else default_sensor

    # ---- Smoothing ----
    smoothing_level = "5" if smoothing else "5"
    smoothing_delta = "15" if not smoothing else "5"

    esc_name = _xml_esc(name)

    # Build the full XML matching Krita's native preset format.
    params = [
        ("ColorSource/Type", "plain"),
        ("CompositeOp", "normal"),
        # Curve* — "same curve" fallback for each sensor group
        ("CurveDarken", "0,0;1,1;"),
        ("CurveMirror", "0,0;1,1;"),
        ("CurveMix", "0,0;1,1;"),
        ("CurveOpacity", "0,0;1,1;"),
        ("CurveRotation", "0,0;1,1;"),
        ("CurveScatter", "0,0;1,1;"),
        ("CurveSharpness", "0,0;1,1;"),
        ("CurveSize", "0,0;1,1;"),
        ("CurveSoftness", "0,0;1,1;"),
        ("Curveh", "0,0;1,1;"),
        ("Curves", "0,0;1,1;"),
        ("Curvev", "0,0;1,1;"),
        # Custom* — enable custom sensor curves
        ("CustomDarken", "true"),
        ("CustomMirror", "true"),
        ("CustomMix", "true"),
        ("CustomOpacity", "true"),
        ("CustomRotation", "true"),
        ("CustomScatter", "true"),
        ("CustomSharpness", "true"),
        ("CustomSize", "true"),
        ("CustomSoftness", "true"),
        ("Customh", "true"),
        ("Customs", "true"),
        ("Customv", "true"),
        # Darken sensor group
        ("DarkenSensor", default_sensor),
        ("DarkenUseCurve", "true"),
        ("DarkenUseSameCurve", "true"),
        ("DarkenValue", "1"),
        ("EraserMode", "false"),
        # Flow sensor group
        ("FlowSensor", flow_sensor),
        ("FlowUseCurve", flow_use_curve),
        ("FlowUseSameCurve", "true"),
        ("FlowValue", f"{flow:.4f}"),
        # Flip X/Y → HorizontalMirrorEnabled / VerticalMirrorEnabled
        ("HorizontalMirrorEnabled", "true" if flip_x else "false"),
        # Smoothing options
        ("KisPrecisionOption/AutoPrecisionEnabled", "true"),
        ("KisPrecisionOption/DeltaValue", smoothing_delta),
        ("KisPrecisionOption/SizeToStartFrom", "10"),
        ("KisPrecisionOption/precisionLevel", smoothing_level),
        # Masking brush (dual brush)
        ("MaskingBrush/Enabled", "true" if masking_enabled else "false"),
        # Mirror sensor group (per-dab flip via random sensor)
        ("MirrorSensor", mirror_sensor),
        ("MirrorUseCurve", "true"),
        ("MirrorUseSameCurve", "true"),
        ("MirrorValue", "1"),
        # Mix sensor group
        ("MixSensor", default_sensor),
        ("MixUseCurve", "true"),
        ("MixUseSameCurve", "true"),
        ("MixValue", "1"),
        # Opacity sensor group
        ("OpacitySensor", opacity_sensor),
        ("OpacityUseCurve", opacity_use_curve),
        ("OpacityUseSameCurve", "true"),
        ("OpacityValue", f"{opacity:.4f}"),
        ("PaintOpAction", "2"),
        ("PaintOpSettings/ignoreSpacing", "false"),
        # Airbrush mode
        ("PaintOpSettings/isAirbrushing", "true" if airbrush else "false"),
        ("PaintOpSettings/rate", "20"),
        ("PaintOpSettings/updateSpacingBetweenDabs", "false"),
        # Pressure flags for each property
        ("PressureDarken", "false"),
        ("PressureMirror", "false"),
        ("PressureMix", "false"),
        ("PressureOpacity", pressure_opacity),
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
        # Ratio sensor group (roundness + optional jitter)
        ("RatioSensor", ratio_sensor),
        ("RatioUseCurve", ratio_use_curve),
        ("RatioUseSameCurve", "true"),
        ("RatioValue", f"{ratio:.4f}"),
        # Rotation sensor group (angle jitter → random)
        ("RotationSensor", rotation_sensor),
        ("RotationUseCurve", rotation_use_curve),
        ("RotationUseSameCurve", "true"),
        ("RotationValue", f"{angle_jitter:.4f}" if angle_jitter > 0 else "1"),
        # Scatter sensor group
        ("ScatterSensor", scatter_sensor),
        ("ScatterUseCurve", scatter_use_curve),
        ("ScatterUseSameCurve", "true"),
        ("ScatterValue", f"{scatter_val:.4f}" if has_scatter else "0"),
        ("Scattering/AxisX", "true"),
        ("Scattering/AxisY", "true" if scatter_both else "false"),
        # Sharpness sensor group
        ("Sharpness/threshold", "40"),
        ("SharpnessSensor", default_sensor),
        ("SharpnessUseCurve", "false"),
        ("SharpnessUseSameCurve", "true"),
        ("SharpnessValue", "1"),
        # Size sensor group (pressure + optional jitter)
        ("SizeSensor", size_sensor),
        ("SizeUseCurve", size_use_curve),
        ("SizeUseSameCurve", "true"),
        ("SizeValue", "1"),
        # Softness sensor group
        ("SoftnessSensor", default_sensor),
        ("SoftnessUseCurve", "true"),
        ("SoftnessUseSameCurve", "true"),
        ("SoftnessValue", "1"),
        # Spacing sensor group
        ("Spacing/Isotropic", "false"),
        ("SpacingSensor", default_sensor),
        ("SpacingUseCurve", "true"),
        ("SpacingUseSameCurve", "true"),
        ("SpacingValue", "1"),
        # Texture overlay
        ("Texture/Pattern/Enabled", "true" if texture_enabled else "false"),
    ]

    # Add texture params when enabled
    if texture_enabled:
        params.extend([
            ("Texture/Pattern/Scale", f"{texture_scale:.4f}"),
            ("Texture/Pattern/MaximumOffsetX", "0"),
            ("Texture/Pattern/MaximumOffsetY", "0"),
            ("Texture/Pattern/isNormalized", "false"),
            ("Texture/Pattern/CutoffPolicy", "0"),
            ("Texture/Pattern/CutoffLeft", "0"),
            ("Texture/Pattern/CutoffRight", "255"),
            ("Texture/Pattern/Invert", "false"),
            ("Texture/Strength/UseSameCurve", "true"),
            ("Texture/Strength/Sensor", default_sensor),
            ("Texture/Strength/UseCurve", "true"),
            ("Texture/Strength/Value", f"{texture_depth:.4f}"),
            ("Texture/Mode", "0"),
        ])

    params.extend([
        # Flip Y → VerticalMirrorEnabled
        ("VerticalMirrorEnabled", "true" if flip_y else "false"),
        ("brush_definition", brush_def + " "),
        # h/s/v sensor groups (color dynamics via random jitter)
        ("hSensor", h_sensor),
        ("hUseCurve", "true"),
        ("hUseSameCurve", "true"),
        ("hValue", f"{hue_jitter:.4f}" if hue_jitter > 0 else "1"),
        ("lodUserAllowed", "true"),
        ("paintop", "paintbrush"),
        ("requiredBrushFile", tip_filename),
        # s sensor group
        ("sSensor", s_sensor),
        ("sUseCurve", "true"),
        ("sUseSameCurve", "true"),
        ("sValue", f"{sat_jitter:.4f}" if sat_jitter > 0 else "1"),
        # v sensor group
        ("vSensor", v_sensor),
        ("vUseCurve", "true"),
        ("vUseSameCurve", "true"),
        ("vValue", f"{val_jitter:.4f}" if val_jitter > 0 else "1"),
    ])

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
