"""
Krita Preset (.kpp) writer.

A Krita 5.x .kpp file is a **PNG image** (200×200 thumbnail) with a
``zTXt`` chunk (keyword ``"preset"``) containing zlib-compressed XML
preset settings.  The brush tip itself lives as a separate ``.gbr``
file in ``brushes/`` and is referenced by filename inside the XML.

Two paint engines are supported:

* ``paintbrush`` — the default pixel brush engine.  Maps ABR brush
  properties (spacing, opacity, flow, size, angle) directly to Krita's
  preset parameters so dynamics are preserved — something GIMP cannot
  do with ABR files.  Optional dry-media modes (chalk, charcoal, conté,
  pencil, colored pencil, ink, spray, airbrush, marker) overlay texture
  grain or change composite / scatter / airbrush behaviour.

* ``colorsmudge`` — Krita's colour-smudge engine.  Produces presets
  where paint mixes on the canvas.  Modes: ``"smudge"`` (gouache / oil),
  ``"wash"`` (watercolour), ``"oil_thick"`` (heavy palette knife),
  ``"acrylic"`` (opaque, less mixing), ``"tempera"`` (fast-drying, matte),
  ``"encaustic"`` (hot wax, heavy drag), ``"fresco"`` (wet plaster).
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
              preset_name: Optional[str] = None,
              masking_tip_override: Optional[str] = None,
              paint_mode: Optional[str] = None) -> None:
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
    paint_mode : str, optional
        ``None`` or ``"pixel"`` → paintbrush engine (default).
        ``"smudge"`` → colorsmudge (gouache / oil — opaque mixing).
        ``"wash"`` → colorsmudge (watercolour — translucent washes).
        ``"oil_thick"`` → colorsmudge (heavy oil — palette knife).
        ``"acrylic"`` → colorsmudge (opaque, less mixing).
        ``"tempera"`` → colorsmudge (fast-drying, minimal mixing).
        ``"encaustic"`` → colorsmudge (hot wax, thick textured mixing).
        ``"fresco"`` → colorsmudge (wet plaster, medium mixing).
        ``"chalk"`` → paintbrush with textured grain overlay.
        ``"charcoal"`` → paintbrush with heavy textured grain.
        ``"conte"`` → paintbrush with dense chalky grain.
        ``"pencil"`` → paintbrush with fine texture, low flow.
        ``"colored_pencil"`` → paintbrush with light texture, medium flow.
        ``"ink"`` → paintbrush with sharp edges, full opacity.
        ``"spray"`` → paintbrush with scatter and airbrush mode.
        ``"airbrush_soft"`` → paintbrush with airbrush mode, soft edges.
        ``"marker"`` → paintbrush with flat strokes (darken composite).
    """
    _colorsmudge_modes = ("smudge", "wash", "oil_thick", "acrylic",
                          "tempera", "encaustic", "fresco")
    if paint_mode in _colorsmudge_modes:
        return _write_kpp_colorsmudge(filepath, tip, invert, use_pressure,
                                      preset_name, paint_mode)

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

    # --- Purity (foreground/background mixing) ---
    purity = dyn.purity if dyn else 0
    use_gradient = purity != 0
    # Map PS purity -100..100 → Krita mix 0..1
    # purity>0 = bias foreground (mix→1), purity<0 = bias bg (mix→0)
    mix_value = (purity + 100) / 200.0 if use_gradient else 0.5

    # --- Texture ---
    texture_enabled = dyn.texture_enabled if dyn else False
    texture_pattern = dyn.texture_pattern_name if dyn else ""
    texture_scale = (dyn.texture_scale / 100.0) if dyn else 1.0
    texture_depth = (dyn.texture_depth / 100.0) if dyn else 1.0

    # --- Masking brush (dual brush) ---
    masking_enabled = dyn.dual_brush_enabled if dyn else False
    masking_composite = "multiply"
    masking_scatter = 0.0
    masking_scatter_both = False
    masking_spacing = 0.25
    masking_flip = False
    masking_ratio = 1.0
    masking_angle = 0
    masking_tip = masking_tip_override or tip_filename
    if dyn and dyn.dual_brush_enabled:
        # Map PS blend mode → Krita composite op
        _mode_map = {
            "multiply": "multiply", "darken": "darken",
            "colorBurn": "burn", "linearBurn": "linear_burn",
            "lighten": "lighten", "screen": "screen",
            "colorDodge": "dodge", "linearDodge": "linear_dodge",
            "overlay": "overlay", "softLight": "soft_light",
            "hardLight": "hard_light", "vividLight": "vivid_light",
            "linearLight": "linear_light", "pinLight": "pin_light",
            "hardMix": "hard_mix", "difference": "diff",
            "exclusion": "exclusion", "subtract": "subtract",
            "divide": "divide",
        }
        masking_composite = _mode_map.get(dyn.dual_brush_mode, "multiply")
        masking_scatter = dyn.dual_brush_scatter / 100.0
        masking_scatter_both = dyn.dual_brush_scatter > 0
        masking_spacing = max(0.01, dyn.dual_brush_spacing / 100.0)
        masking_flip = dyn.dual_brush_flip
        masking_ratio = dyn.dual_brush_roundness / 100.0
        masking_angle = dyn.dual_brush_angle

    # --- Noise → texture overlay fallback ---
    noise = dyn.noise if dyn else False
    if noise and not texture_enabled:
        texture_enabled = True
        texture_scale = 0.15   # fine grain
        texture_depth = 0.30   # subtle
        texture_pattern = "06_hard-grain"  # grain pattern approximates PS noise

    # --- Paint mode overrides for dry / specialty media ---
    composite_override = "normal"
    flow_override = None  # None means use ABR value
    if paint_mode == "chalk":
        texture_enabled = True
        texture_scale = max(texture_scale, 1.0)
        texture_depth = max(texture_depth, 0.80)
        if not texture_pattern:
            texture_pattern = "10_drawed_dotted"
    elif paint_mode == "charcoal":
        texture_enabled = True
        texture_scale = 0.35
        texture_depth = max(texture_depth, 0.90)
        if not texture_pattern:
            texture_pattern = "10_drawed_dotted"
    elif paint_mode == "conte":
        texture_enabled = True
        texture_scale = 0.50
        texture_depth = max(texture_depth, 0.85)
        if not texture_pattern:
            texture_pattern = "10_drawed_dotted"
    elif paint_mode == "pencil":
        texture_enabled = True
        texture_scale = 0.20
        texture_depth = max(texture_depth, 0.50)
        flow_override = 0.4
        if not texture_pattern:
            texture_pattern = "06_hard-grain"
    elif paint_mode == "colored_pencil":
        texture_enabled = True
        texture_scale = 0.25
        texture_depth = max(texture_depth, 0.40)
        flow_override = 0.6
        if not texture_pattern:
            texture_pattern = "06_hard-grain"
    elif paint_mode == "ink":
        flow_override = 1.0
        opacity = 1.0
        opacity_curve = None  # No pressure on opacity — sharp, solid strokes
    elif paint_mode == "spray":
        airbrush = True
        if scatter_val < 1.5:
            scatter_val = 1.5
        scatter_both = True
        opacity = min(opacity, 0.6)
    elif paint_mode == "airbrush_soft":
        airbrush = True
        opacity = min(opacity, 0.8)
    elif paint_mode == "marker":
        composite_override = "darken"
        flow_override = 1.0
        opacity = 1.0
        # Disable pressure on opacity for flat marker strokes
        opacity_curve = None

    # Apply flow override from paint mode
    if flow_override is not None:
        flow = flow_override

    # --- Wet edges → softness + darken edge simulation ---
    wet_edges = dyn.wet_edges if dyn else False

    # --- Resolve texture pattern filename ---
    texture_pattern_file = _resolve_pattern_filename(texture_pattern) if texture_enabled else ""

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
        composite_op=composite_override,
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
        texture_pattern_file=texture_pattern_file,
        texture_scale=texture_scale,
        texture_depth=texture_depth,
        masking_enabled=masking_enabled,
        masking_composite=masking_composite,
        masking_tip_filename=masking_tip,
        masking_scatter=masking_scatter,
        masking_scatter_both=masking_scatter_both,
        masking_spacing=masking_spacing,
        masking_flip=masking_flip,
        masking_ratio=masking_ratio,
        masking_angle=masking_angle,
        wet_edges=wet_edges,
        use_gradient=use_gradient,
        mix_value=mix_value,
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
                     composite_op: str = "normal",
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
                     texture_pattern_file: str = "",
                     texture_scale: float = 1.0,
                     texture_depth: float = 1.0,
                     masking_enabled: bool = False,
                     masking_composite: str = "multiply",
                     masking_tip_filename: str = "",
                     masking_scatter: float = 0.0,
                     masking_scatter_both: bool = False,
                     masking_spacing: float = 0.25,
                     masking_flip: bool = False,
                     masking_ratio: float = 1.0,
                     masking_angle: int = 0,
                     wet_edges: bool = False,
                     use_gradient: bool = False,
                     mix_value: float = 0.5,
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

    # ---- Mix sensor (purity / fg-bg jitter) ----
    if use_gradient:
        mix_sensor = _sensor("random")
    else:
        mix_sensor = default_sensor

    # ---- Smoothing ----
    smoothing_level = "5" if smoothing else "5"
    smoothing_delta = "15" if not smoothing else "5"

    esc_name = _xml_esc(name)

    # Build the full XML matching Krita's native preset format.
    params = [
        ("ColorSource/Type", "gradient" if use_gradient else "plain"),
        ("CompositeOp", composite_op),
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
        # Darken sensor group — wet edges → darken at edges for buildup
        ("DarkenSensor", default_sensor),
        ("DarkenUseCurve", "true"),
        ("DarkenUseSameCurve", "true"),
        ("DarkenValue", "0.85" if wet_edges else "1"),
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
        # Masking brush (dual brush) — full preset when enabled
        ("MaskingBrush/Enabled", "true" if masking_enabled else "false"),
    ]

    if masking_enabled and masking_tip_filename:
        # Build the masking brush definition referencing the same GBR tip
        mask_brush_def = (
            f'<Brush type="gbr_brush" BrushVersion="2"'
            f' filename="{_xml_esc(masking_tip_filename)}"'
            f' spacing="{masking_spacing:.4f}"'
            f' useAutoSpacing="0" autoSpacingCoeff="1"'
            f' angle="{masking_angle}" scale="1"'
            f' ColorAsMask="1" AdjustmentMidPoint="127"'
            f' BrightnessAdjustment="0" ContrastAdjustment="0"'
            f' preserveLightness="0"/>'
        )
        mask_mirror = _sensor("random") if masking_flip else _sensor("pressure")
        mask_scatter_val = f"{masking_scatter:.4f}" if masking_scatter > 0 else "0"
        params.extend([
            ("MaskingBrush/MaskingCompositeOp", masking_composite),
            ("MaskingBrush/MasterSizeCoeff", "1"),
            ("MaskingBrush/Preset/FlowSensor", default_sensor),
            ("MaskingBrush/Preset/FlowUseCurve", "false"),
            ("MaskingBrush/Preset/FlowUseSameCurve", "true"),
            ("MaskingBrush/Preset/FlowValue", "1"),
            ("MaskingBrush/Preset/HorizontalMirrorEnabled",
             "true" if masking_flip else "false"),
            ("MaskingBrush/Preset/MirrorSensor", mask_mirror),
            ("MaskingBrush/Preset/MirrorUseCurve", "true"),
            ("MaskingBrush/Preset/MirrorUseSameCurve", "true"),
            ("MaskingBrush/Preset/MirrorValue", "1"),
            ("MaskingBrush/Preset/OpacitySensor", default_sensor),
            ("MaskingBrush/Preset/OpacityUseCurve", "false"),
            ("MaskingBrush/Preset/OpacityUseSameCurve", "true"),
            ("MaskingBrush/Preset/OpacityValue", "1"),
            ("MaskingBrush/Preset/PressureMirror", "false"),
            ("MaskingBrush/Preset/PressureRatio", "false"),
            ("MaskingBrush/Preset/PressureRotation", "false"),
            ("MaskingBrush/Preset/PressureScatter", "false"),
            ("MaskingBrush/Preset/PressureSize", "false"),
            ("MaskingBrush/Preset/RatioSensor", _sensor("pressure")),
            ("MaskingBrush/Preset/RatioUseCurve", "true"),
            ("MaskingBrush/Preset/RatioUseSameCurve", "true"),
            ("MaskingBrush/Preset/RatioValue", f"{masking_ratio:.4f}"),
            ("MaskingBrush/Preset/RotationSensor", _sensor("pressure")),
            ("MaskingBrush/Preset/RotationUseCurve", "true"),
            ("MaskingBrush/Preset/RotationUseSameCurve", "true"),
            ("MaskingBrush/Preset/RotationValue", "1"),
            ("MaskingBrush/Preset/ScatterSensor", default_sensor),
            ("MaskingBrush/Preset/ScatterUseCurve",
             "true" if masking_scatter > 0 else "false"),
            ("MaskingBrush/Preset/ScatterUseSameCurve", "true"),
            ("MaskingBrush/Preset/ScatterValue", mask_scatter_val),
            ("MaskingBrush/Preset/Scattering/AxisX", "true"),
            ("MaskingBrush/Preset/Scattering/AxisY",
             "true" if masking_scatter_both else "false"),
            ("MaskingBrush/Preset/SizeSensor", default_sensor),
            ("MaskingBrush/Preset/SizeUseCurve", "false"),
            ("MaskingBrush/Preset/SizeUseSameCurve", "true"),
            ("MaskingBrush/Preset/SizeValue", "1"),
            ("MaskingBrush/Preset/VerticalMirrorEnabled", "false"),
            ("MaskingBrush/Preset/brush_definition", mask_brush_def + " "),
            ("MaskingBrush/Preset/requiredBrushFile", masking_tip_filename),
            ("MaskingBrush/UseMasterSize", "true"),
        ])

    params.extend([
        # Mirror sensor group (per-dab flip via random sensor)
        ("MirrorSensor", mirror_sensor),
        ("MirrorUseCurve", "true"),
        ("MirrorUseSameCurve", "true"),
        ("MirrorValue", "1"),
        # Mix sensor group (fg/bg mixing via purity)
        ("MixSensor", mix_sensor),
        ("MixUseCurve", "true"),
        ("MixUseSameCurve", "true"),
        ("MixValue", f"{mix_value:.4f}" if use_gradient else "1"),
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
        # Softness sensor group — wet edges → reduced softness for edge buildup
        ("SoftnessSensor", default_sensor),
        ("SoftnessUseCurve", "true"),
        ("SoftnessUseSameCurve", "true"),
        ("SoftnessValue", "0.5" if wet_edges else "1"),
        # Spacing sensor group
        ("Spacing/Isotropic", "false"),
        ("SpacingSensor", default_sensor),
        ("SpacingUseCurve", "true"),
        ("SpacingUseSameCurve", "true"),
        ("SpacingValue", "1"),
        # Texture overlay
        ("Texture/Pattern/Enabled", "true" if texture_enabled else "false"),
    ])

    # Add texture params when enabled
    if texture_enabled:
        tex_params = [
            ("Texture/Pattern/Scale", f"{texture_scale:.4f}"),
            ("Texture/Pattern/MaximumOffsetX", "0"),
            ("Texture/Pattern/MaximumOffsetY", "0"),
            ("Texture/Pattern/isNormalized", "false"),
            ("Texture/Pattern/CutoffPolicy", "0"),
            ("Texture/Pattern/CutoffLeft", "0"),
            ("Texture/Pattern/CutoffRight", "255"),
            ("Texture/Pattern/Invert", "false"),
        ]
        if texture_pattern_file:
            tex_params.append(
                ("Texture/Pattern/PatternFileName", texture_pattern_file))
        tex_params.extend([
            ("Texture/Strength/UseSameCurve", "true"),
            ("Texture/Strength/Sensor", default_sensor),
            ("Texture/Strength/UseCurve", "true"),
            ("Texture/Strength/Value", f"{texture_depth:.4f}"),
            ("Texture/Mode", "0"),
        ])
        params.extend(tex_params)

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
#  Color-smudge preset writer (gouache / oil / watercolour)            #
# ------------------------------------------------------------------ #

def _write_kpp_colorsmudge(filepath: str, tip: BrushTip, invert: bool,
                           use_pressure: bool, preset_name: Optional[str],
                           paint_mode: str) -> None:
    """Write a .kpp using the ``colorsmudge`` engine."""
    name = preset_name or tip.name or "Imported Brush"
    safe = _sanitize_filename(name)
    tip_filename = f"{safe}.gbr"

    size = float(max(tip.width, tip.height, 1))
    spacing = max(0.01, tip.spacing / 100.0)
    dyn: Optional[BrushDynamics] = tip.dynamics
    opacity = (dyn.opacity / 100.0) if dyn else 1.0

    preset_xml = _make_colorsmudge_xml(
        name=name,
        tip_filename=tip_filename,
        size=size,
        spacing=spacing,
        opacity=opacity,
        use_pressure=use_pressure,
        paint_mode=paint_mode,
    )

    png_bytes = _make_kpp_png(tip, invert, preset_xml)
    _ensure_dir(filepath)
    with open(filepath, 'wb') as fh:
        fh.write(png_bytes)


def _make_colorsmudge_xml(name: str, tip_filename: str, size: float,
                          spacing: float, opacity: float,
                          use_pressure: bool, paint_mode: str) -> str:
    """Build Krita 5.x preset XML for the ``colorsmudge`` engine.

    *paint_mode* controls the smudge/colour balance:

    * ``"smudge"`` — opaque gouache/oil: high colour rate, moderate
      smudge rate, paint covers layers below and mixes on canvas.
    * ``"wash"`` — translucent watercolour: low colour rate, higher
      smudge rate, strokes layer transparently with fringe effects.
    * ``"oil_thick"`` — heavy oil / palette knife: wide pickup radius,
      thick paint mixing like a painting knife.
    * ``"acrylic"`` — opaque like gouache but with reduced smudge rate,
      simulating fast-drying acrylic with less wet-on-wet mixing.
    * ``"tempera"`` — egg tempera: fast-drying, minimal mixing, matte
      finish, high colour rate with almost no smudge.
    * ``"encaustic"`` — hot wax paint: thick, textured, wide smudge
      radius like a palette knife but with more drag.
    * ``"fresco"`` — pigment on wet plaster: medium mixing, slightly
      translucent, colours absorb into the surface.
    """
    esc_name = _xml_esc(name)

    # Brush definition — reference the .gbr file
    brush_def = (
        f'<Brush type="gbr_brush" BrushVersion="2"'
        f' filename="{_xml_esc(tip_filename)}"'
        f' spacing="{spacing:.4f}"'
        f' useAutoSpacing="0" autoSpacingCoeff="1"'
        f' angle="0" scale="1"'
        f' ColorAsMask="1" AdjustmentMidPoint="127"'
        f' BrightnessAdjustment="0" ContrastAdjustment="0"'
        f' preserveLightness="0"/>'
    )

    # Sensor helper
    def _sensor(sensor_id="pressure", curve_pts=None):
        if curve_pts:
            c = ";".join(f"{x},{y}" for x, y in curve_pts) + ";"
            return (f'<!DOCTYPE params> <params id="{sensor_id}">'
                    f' <curve>{c}</curve> </params> ')
        return f'<!DOCTYPE params> <params id="{sensor_id}"/> '

    linear = [(0, 0), (1, 1)]
    default_sensor = _sensor("pressure", linear)

    # Mode-specific tuning — based on Krita's built-in wet-paint and
    # watercolour presets.
    if paint_mode == "wash":
        # Watercolour: translucent, more smudging, lower colour rate
        color_rate_val = "0.5"
        smudge_rate_val = "1"
        smudge_radius_val = "0.41"
        smudge_mode = "1"
        smudge_rate_curve = [(0, 0.056), (0.55, 0.537), (1, 1)]
        opacity_val = f"{opacity:.4f}"
    elif paint_mode == "oil_thick":
        # Heavy oil / palette knife: thick mixing, wide pickup radius
        color_rate_val = "0.7"
        smudge_rate_val = "1"
        smudge_radius_val = "9.23"
        smudge_mode = "1"
        smudge_rate_curve = [(0, 0.08), (0.13, 0.285), (0.71, 1), (1, 1)]
        opacity_val = f"{opacity:.4f}"
    elif paint_mode == "acrylic":
        # Acrylic: opaque, quick-drying — less mixing than oil/gouache
        color_rate_val = "1"
        smudge_rate_val = "0.4"
        smudge_radius_val = "0.2"
        smudge_mode = "0"
        smudge_rate_curve = [(0, 0.0), (0.3, 0.15), (0.7, 0.35), (1, 0.5)]
        opacity_val = f"{opacity:.4f}"
    elif paint_mode == "tempera":
        # Tempera: egg-based, fast-drying, almost no wet mixing, matte
        color_rate_val = "1"
        smudge_rate_val = "0.15"
        smudge_radius_val = "0.1"
        smudge_mode = "0"
        smudge_rate_curve = [(0, 0.0), (0.5, 0.08), (1, 0.2)]
        opacity_val = f"{opacity:.4f}"
    elif paint_mode == "encaustic":
        # Encaustic: hot wax, thick, heavy drag mixing, wide pickup
        color_rate_val = "0.8"
        smudge_rate_val = "1"
        smudge_radius_val = "5.0"
        smudge_mode = "1"
        smudge_rate_curve = [(0, 0.15), (0.2, 0.5), (0.6, 0.85), (1, 1)]
        opacity_val = f"{opacity:.4f}"
    elif paint_mode == "fresco":
        # Fresco: pigment on wet plaster, medium mixing, slightly translucent
        color_rate_val = "0.7"
        smudge_rate_val = "0.6"
        smudge_radius_val = "0.3"
        smudge_mode = "1"
        smudge_rate_curve = [(0, 0.05), (0.4, 0.35), (0.8, 0.6), (1, 0.75)]
        opacity_val = f"{opacity:.4f}"
    else:
        # Gouache/oil: opaque, full colour rate, moderate smudge
        color_rate_val = "1"
        smudge_rate_val = "1"
        smudge_radius_val = "0.41"
        smudge_mode = "1"
        smudge_rate_curve = [(0, 0.08), (0.13, 0.285), (0.71, 1), (1, 1)]
        opacity_val = f"{opacity:.4f}"

    # Size sensor
    if use_pressure:
        size_sensor = _sensor("pressure", linear)
        pressure_size = "true"
        size_use_curve = "true"
    else:
        size_sensor = _sensor("pressure")
        pressure_size = "false"
        size_use_curve = "false"

    # Opacity sensor — gentle ramp so light pressure still paints
    opacity_curve = [(0, 0.15), (0.06, 0.26), (0.17, 0.42),
                     (0.23, 0.48), (0.30, 0.53), (1, 1)]
    opacity_sensor = _sensor("pressure", opacity_curve)

    params = [
        # Colour rate (how much foreground colour is deposited)
        ("ColorRateSensor", _sensor("pressure", linear)),
        ("ColorRateUseCurve", "false"),
        ("ColorRateUseSameCurve", "true"),
        ("ColorRateValue", color_rate_val),
        ("ColorRatecurveMode", "0"),
        ("CompositeOp", "normal"),
        ("EraserMode", "false"),
        ("GradientSensor", _sensor("pressure")),
        ("GradientUseCurve", "true"),
        ("GradientUseSameCurve", "true"),
        ("GradientValue", "1"),
        ("GradientcurveMode", "0"),
        ("HorizontalMirrorEnabled", "false"),
        ("KisPrecisionOption/AutoPrecisionEnabled", "false"),
        ("KisPrecisionOption/DeltaValue", "15"),
        ("KisPrecisionOption/SizeToStartFrom", "0"),
        ("KisPrecisionOption/precisionLevel", "5"),
        ("MergedPaint", "false"),
        ("MirrorSensor", _sensor("pressure")),
        ("MirrorUseCurve", "true"),
        ("MirrorUseSameCurve", "true"),
        ("MirrorValue", "1"),
        ("MirrorcurveMode", "0"),
        # Opacity — pressure-sensitive with gentle ramp
        ("OpacitySensor", opacity_sensor),
        ("OpacityUseCurve", "true"),
        ("OpacityUseSameCurve", "true"),
        ("OpacityValue", opacity_val),
        ("OpacityVersion", "2"),
        ("OpacitycurveMode", "0"),
        ("PaintOpSettings/updateSpacingBetweenDabs", "false"),
        ("PressureColorRate", "true"),
        ("PressureGradient", "false"),
        ("PressureMirror", "false"),
        ("PressureRotation", "false"),
        ("PressureScatter", "false"),
        ("PressureSize", pressure_size),
        ("PressureSmudgeRadius", "true"),
        ("PressureSmudgeRate", "true"),
        ("PressureSpacing", "false"),
        ("PressureTexture/Strength/", "false"),
        ("RotationSensor", _sensor("pressure")),
        ("RotationUseCurve", "true"),
        ("RotationUseSameCurve", "true"),
        ("RotationValue", "1"),
        ("RotationcurveMode", "0"),
        ("ScatterSensor", default_sensor),
        ("ScatterUseCurve", "false"),
        ("ScatterUseSameCurve", "true"),
        ("ScatterValue", "1"),
        ("ScattercurveMode", "0"),
        ("Scattering/AxisX", "true"),
        ("Scattering/AxisY", "true"),
        # Size — pressure
        ("SizeSensor", size_sensor),
        ("SizeUseCurve", size_use_curve),
        ("SizeUseSameCurve", "true"),
        ("SizeValue", "1"),
        ("SizecurveMode", "0"),
        # Smudge radius — how far paint picks up from canvas
        ("SmudgeRadiusSensor", _sensor("pressure")),
        ("SmudgeRadiusUseCurve", "false"),
        ("SmudgeRadiusUseSameCurve", "true"),
        ("SmudgeRadiusValue", smudge_radius_val),
        ("SmudgeRadiuscurveMode", "0"),
        # Smudge rate — how much existing paint is mixed in
        ("SmudgeRateMode", smudge_mode),
        ("SmudgeRateSensor", _sensor("pressure", smudge_rate_curve)),
        ("SmudgeRateUseCurve", "true"),
        ("SmudgeRateUseSameCurve", "true"),
        ("SmudgeRateValue", smudge_rate_val),
        ("SmudgeRatecurveMode", "0"),
        ("Spacing/Isotropic", "false"),
        ("SpacingSensor", _sensor("pressure")),
        ("SpacingUseCurve", "true"),
        ("SpacingUseSameCurve", "true"),
        ("SpacingValue", "1"),
        ("SpacingcurveMode", "0"),
        ("Texture/Pattern/Enabled", "false"),
        ("VerticalMirrorEnabled", "false"),
        ("brush_definition", brush_def + " "),
        ("paintop", "colorsmudge"),
        ("requiredBrushFile", tip_filename),
        ("requiredBrushFilesList", ""),
    ]

    parts = [f'<Preset name="{esc_name}" paintopid="colorsmudge">']
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


def _resolve_pattern_filename(pattern_name: str) -> str:
    """Try to find a matching Krita pattern file for the given PS pattern name.

    Searches the standard Krita patterns directories for files whose
    stem (without extension) contains the pattern name (case-insensitive).
    Returns the filename (not full path) if found, empty string otherwise.
    """
    if not pattern_name:
        return ""

    import glob as _glob

    # Standard Krita pattern directories (Flatpak + system)
    search_dirs = [
        os.path.expanduser("~/.var/app/org.kde.krita/data/krita/patterns"),
        os.path.expanduser("~/.local/share/krita/patterns"),
        "/usr/share/krita/patterns",
    ]

    needle = pattern_name.lower().replace(" ", "").replace("_", "")
    best_match = ""

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            stem = os.path.splitext(entry)[0].lower().replace(" ", "").replace("_", "")
            # Exact stem match
            if stem == needle:
                return entry
            # Partial match (PS name is substring of Krita pattern name or vice versa)
            if needle in stem or stem in needle:
                if not best_match or len(entry) < len(best_match):
                    best_match = entry

    return best_match


def _sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:80] if safe else "brush"


def _ensure_dir(filepath: str) -> None:
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)
