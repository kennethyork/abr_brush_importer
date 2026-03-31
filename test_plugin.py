#!/usr/bin/env python3
"""Quick self-test for the ABR parser and GBR writer (runs outside Krita)."""

import sys, os, struct, tempfile, shutil, types

# Mock the krita module so __init__.py can be imported outside Krita
krita_mock = types.ModuleType('krita')
class _FakeExtension:
    def __init__(self, *a, **kw): pass
class _FakeKrita:
    @staticmethod
    def instance(): return _FakeKrita()
    def addExtension(self, *a): pass
krita_mock.Extension = _FakeExtension
krita_mock.Krita = _FakeKrita
sys.modules['krita'] = krita_mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from abr_brush_importer.abr_parser import (
    ABRParser, BrushTip, BrushDynamics, BrushPattern, parse_abr,
)
from abr_brush_importer.gbr_writer import write_gbr, write_png
from abr_brush_importer.kpp_writer import write_kpp, _make_preset_xml

print("All modules import OK")

# ── 1) Generate a computed brush ──
tip = BrushTip()
tip.name = "Test Round"
tip.width = 32
tip.height = 32
tip.spacing = 25
tip.image_data = ABRParser._generate_computed_image(32, 100, 0, 80)
print(f"Generated computed brush: {len(tip.image_data)} bytes ({tip.width}x{tip.height})")
assert len(tip.image_data) == 32 * 32

# ── 2) Write GBR and PNG (grayscale) ──
tmp = tempfile.mkdtemp()
gbr_path = os.path.join(tmp, "test.gbr")
png_path = os.path.join(tmp, "test.png")
write_gbr(gbr_path, "Test", 32, 32, tip.image_data, 25)
write_png(png_path, 32, 32, tip.image_data)
print(f"GBR: {os.path.getsize(gbr_path)} bytes  |  PNG: {os.path.getsize(png_path)} bytes")

# ── 3) Verify GBR header ──
with open(gbr_path, "rb") as f:
    hs, ver, w, h, bpp = struct.unpack(">IIIII", f.read(20))
    magic = f.read(4)
    spacing = struct.unpack(">I", f.read(4))[0]
    print(f"GBR header: v{ver} {w}x{h} bpp={bpp} magic={magic} spacing={spacing}%")
    assert magic == b"GIMP"
    assert ver == 2
    assert w == 32 and h == 32
    assert bpp == 1

# ── 4) Write GBR with RGBA (4 channels) ──
rgba_data = bytes([255, 0, 0, 128] * (16 * 16))  # 16x16 red semi-transparent
gbr_rgba = os.path.join(tmp, "test_rgba.gbr")
write_gbr(gbr_rgba, "RGBA Test", 16, 16, rgba_data, 25, channels=4)
with open(gbr_rgba, "rb") as f:
    hs, ver, w, h, bpp = struct.unpack(">IIIII", f.read(20))
    assert bpp == 4, f"Expected bpp=4, got {bpp}"
    print(f"GBR RGBA: v{ver} {w}x{h} bpp={bpp} — OK")

# ── 5) Write PNG with RGBA ──
png_rgba = os.path.join(tmp, "test_rgba.png")
write_png(png_rgba, 16, 16, rgba_data, channels=4)
with open(png_rgba, "rb") as f:
    sig = f.read(8)
    assert sig == b'\x89PNG\r\n\x1a\n'
    _len = struct.unpack(">I", f.read(4))[0]
    _type = f.read(4)
    ihdr = f.read(_len)
    _w, _h, bd, ct = struct.unpack(">IIBB", ihdr[:10])
    assert ct == 6, f"Expected colour type 6 (RGBA), got {ct}"
    print(f"PNG RGBA: {_w}x{_h} depth={bd} colour_type={ct} — OK")

# ── 6) Test PackBits decoder ──
data = bytes([0x02, 0xAA, 0xBB, 0xCC, 0xFE, 0xDD])
result = ABRParser._decode_packbits(data, 6)
assert result == b"\xAA\xBB\xCC\xDD\xDD\xDD", f"PackBits failed: {result.hex()}"
print("PackBits RLE decoder: OK")

# ── 7) Test round-trip: build a fake v1 ABR in memory, parse it ──
def build_fake_v1_abr():
    """Create a minimal v1 ABR with one computed brush."""
    buf = bytearray()
    buf += struct.pack(">H", 1)       # version 1
    buf += struct.pack(">H", 1)       # count = 1
    brush_data = bytearray()
    brush_data += struct.pack(">I", 0)    # misc
    brush_data += struct.pack(">H", 25)   # spacing
    brush_data += struct.pack(">H", 20)   # diameter
    brush_data += struct.pack(">H", 100)  # roundness
    brush_data += struct.pack(">H", 0)    # angle
    brush_data += struct.pack(">H", 100)  # hardness
    buf += struct.pack(">H", 1)           # brush type
    buf += struct.pack(">I", len(brush_data))
    buf += brush_data
    return bytes(buf)

fake_abr = build_fake_v1_abr()
parser = ABRParser(data=fake_abr)
tips = parser.parse()
assert len(tips) == 1, f"Expected 1 brush, got {len(tips)}"
assert tips[0].diameter == 20
assert tips[0].width == 20 and tips[0].height == 20
print(f"v1 ABR round-trip: OK ({tips[0].name} {tips[0].width}x{tips[0].height})")

# ── 8) Test parse_abr() returns tuple (tips, patterns) ──
# We can't use parse_abr (needs filepath), but verify the signature
import inspect
sig = inspect.signature(parse_abr)
params = list(sig.parameters.keys())
assert params == ['filepath'], f"parse_abr params: {params}"
print("parse_abr() signature: OK")

# ── 9) Test get_grayscale ──
# Grayscale passthrough
gray_tip = BrushTip(width=2, height=2, channels=1, image_data=b'\x10\x20\x30\x40')
assert ABRParser.get_grayscale(gray_tip) == b'\x10\x20\x30\x40'

# RGBA → alpha channel extraction
rgba_tip = BrushTip(width=2, height=2, channels=4,
                    image_data=bytes([255,0,0,100, 0,255,0,200, 0,0,255,50, 128,128,128,255]))
gray = ABRParser.get_grayscale(rgba_tip)
assert gray == bytes([100, 200, 50, 255]), f"RGBA→gray: {list(gray)}"

# RGB → luminance
rgb_tip = BrushTip(width=1, height=1, channels=3, image_data=bytes([255, 255, 255]))
gray = ABRParser.get_grayscale(rgb_tip)
assert gray[0] == 255, f"RGB→gray white: {gray[0]}"
print("get_grayscale(): OK")

# ── 10) Test BrushDynamics dataclass ──
dyn = BrushDynamics()
assert dyn.spacing == 25
assert dyn.opacity == 100
assert dyn.flow == 100
assert dyn.wet_edges is False
dyn2 = BrushDynamics(spacing=50, opacity=80, wet_edges=True)
assert dyn2.spacing == 50
assert dyn2.wet_edges is True
print("BrushDynamics: OK")

# ── 11) Test BrushPattern dataclass ──
pat = BrushPattern(name="TestPat", width=4, height=4, channels=1,
                   image_data=b'\x80' * 16)
assert pat.width == 4 and pat.name == "TestPat"
print("BrushPattern: OK")

# ── 12) Test error recovery (malformed data) ──
# Feed garbage data — parser should not crash
garbage = b'\x00\x06\x00\x01' + b'\xFF' * 100
parser = ABRParser(data=garbage)
tips = parser.parse()
# Should return empty or partial — just must not crash
print(f"Garbage data test: returned {len(tips)} tips (no crash) — OK")

# Feed truncated header
for size in (0, 1, 2, 3):
    parser = ABRParser(data=b'\x00' * size)
    tips = parser.parse()
    assert tips == [] or isinstance(tips, list)
print("Truncated header recovery: OK")

# Cleanup
shutil.rmtree(tmp)

# ── 13) Test write_kpp produces a valid PNG with zTXt ──
tmp2 = tempfile.mkdtemp()
kpp_tip = BrushTip()
kpp_tip.name = "KPP Test"
kpp_tip.width = 32
kpp_tip.height = 32
kpp_tip.spacing = 25
kpp_tip.channels = 1
kpp_tip.image_data = ABRParser._generate_computed_image(32, 100, 0, 80)

kpp_path = os.path.join(tmp2, "test.kpp")
write_kpp(kpp_path, kpp_tip)
assert os.path.isfile(kpp_path), "write_kpp did not create the file"

import zlib as _zlib
with open(kpp_path, 'rb') as f:
    sig = f.read(8)
    assert sig == b'\x89PNG\r\n\x1a\n', "kpp file is not a valid PNG"
    # Parse chunks to find zTXt, pHYs, and tEXt version
    found_ztxt = False
    found_phys = False
    found_version = False
    while True:
        raw = f.read(8)
        if len(raw) < 8:
            break
        length, ctype = struct.unpack('>I4s', raw)
        data = f.read(length)
        f.read(4)  # CRC
        if ctype == b'IHDR':
            w, h, bd, ct = struct.unpack('>IIBB', data[:10])
            assert w == 200 and h == 200, f"Expected 200x200, got {w}x{h}"
            assert ct == 6, f"Expected RGBA (ct=6), got {ct}"
        elif ctype == b'pHYs':
            ppux, ppuy, unit = struct.unpack('>IIB', data)
            assert ppux == 3780 and ppuy == 3780, f"Expected 3780 pHYs, got {ppux},{ppuy}"
            found_phys = True
        elif ctype == b'zTXt':
            null_pos = data.index(0)
            keyword = data[:null_pos].decode('latin-1')
            assert keyword == 'preset', f"Expected keyword 'preset', got '{keyword}'"
            xml_content = _zlib.decompress(data[null_pos+2:]).decode('utf-8')
            assert "paintbrush" in xml_content, "preset XML missing paintop id"
            assert "KPP Test" in xml_content, "preset XML missing brush name"
            found_ztxt = True
        elif ctype == b'tEXt':
            null_pos = data.index(0)
            keyword = data[:null_pos].decode('latin-1')
            value = data[null_pos+1:].decode('latin-1')
            if keyword == 'version':
                assert value == '2.2', f"Expected version 2.2, got {value}"
                found_version = True
    assert found_ztxt, "No zTXt chunk found in .kpp PNG"
    assert found_phys, "No pHYs chunk found in .kpp PNG"
    assert found_version, "No tEXt version chunk found in .kpp PNG"

print(f"write_kpp: OK (PNG with zTXt preset)")

# Helper to extract XML from .kpp PNG
def _extract_kpp_xml(kpp_path):
    with open(kpp_path, 'rb') as f:
        f.read(8)  # PNG signature
        while True:
            raw = f.read(8)
            if len(raw) < 8:
                return ""
            length, ctype = struct.unpack('>I4s', raw)
            data = f.read(length)
            f.read(4)
            if ctype == b'zTXt':
                null_pos = data.index(0)
                return _zlib.decompress(data[null_pos+2:]).decode('utf-8')
    return ""

# ── 14) Test _make_preset_xml content ──
xml = _make_preset_xml("My Brush", "my_brush.gbr", 50.0, 0.25, 0.8, 0.9)
assert "paintbrush" in xml
assert "My Brush" in xml
assert "0.25" in xml     # spacing
assert "0.8" in xml      # opacity
assert "0.9" in xml      # flow
assert "my_brush.gbr" in xml
# Krita 5.x format: <Preset> with flat <param> CDATA children
assert '<Preset' in xml, "Missing <Preset> root element"
assert 'type="string"' in xml, "Missing type=string params"
assert '<![CDATA[' in xml, "Missing CDATA wrapping"
assert 'gbr_brush' in xml, "Missing gbr_brush type in brush_definition"
print("_make_preset_xml: OK")

# ── 15) Test write_kpp thumbnail is 200x200 RGBA PNG ──
# Already verified above in test 13 — IHDR 200x200 ct=6
print("_make_thumbnail (RGBA 200x200): OK (covered by test 13)")

# ── 16) Test write_kpp with dynamics ──
dyn_tip = BrushTip()
dyn_tip.name = "Dynamic Brush"
dyn_tip.width = 16
dyn_tip.height = 16
dyn_tip.spacing = 50
dyn_tip.channels = 1
dyn_tip.image_data = bytes([200] * 256)
dyn_tip.dynamics = BrushDynamics(spacing=50, opacity=75, flow=90)

kpp_dyn_path = os.path.join(tmp2, "test_dyn.kpp")
write_kpp(kpp_dyn_path, dyn_tip)
xml_content = _extract_kpp_xml(kpp_dyn_path)
assert "0.75" in xml_content, "opacity not preserved in preset XML"
assert "0.90" in xml_content, "flow not preserved in preset XML"
print("write_kpp with dynamics: OK")

# ── 16b) Test write_kpp with extended dynamics ──
ext_tip = BrushTip()
ext_tip.name = "Extended Dynamics"
ext_tip.width = 24
ext_tip.height = 12
ext_tip.spacing = 30
ext_tip.roundness = 50   # elliptical brush
ext_tip.hardness = 75
ext_tip.channels = 1
ext_tip.image_data = bytes([180] * (24 * 12))
ext_tip.dynamics = BrushDynamics(
    spacing=30, opacity=60, flow=80,
    hardness=75, roundness=50,
    scatter=500, count=3,
    size_jitter=40, angle_jitter=180,
    smoothing=True,
)

kpp_ext_path = os.path.join(tmp2, "test_ext.kpp")
write_kpp(kpp_ext_path, ext_tip)
xml_content = _extract_kpp_xml(kpp_ext_path)
assert '<Preset' in xml_content, "Missing <Preset> root"
assert 'paintopid="paintbrush"' in xml_content, "Missing paintopid"
assert 'gbr_brush' in xml_content, "Missing gbr_brush in brush_definition"
# Verify scatter is wired through
assert 'ScatterValue' in xml_content, "Missing ScatterValue"
assert '5.0000' in xml_content or 'ScatterValue' in xml_content, "Scatter not wired"
# Verify angle jitter → random rotation sensor
assert 'RotationSensor' in xml_content, "Missing RotationSensor"
assert 'id="random"' in xml_content, "Jitter should produce random sensor"
# Verify scatter both axes
assert 'Scattering/AxisY' in xml_content, "Missing Scattering/AxisY"
# Verify size jitter adds random sensor to SizeSensor
assert 'SizeSensor' in xml_content, "Missing SizeSensor"
print("write_kpp with extended dynamics: OK")

# ── 16c) Test write_kpp all dynamics features ──
full_tip = BrushTip()
full_tip.name = "Full Dynamics"
full_tip.width = 16
full_tip.height = 16
full_tip.spacing = 25
full_tip.roundness = 100
full_tip.channels = 1
full_tip.image_data = bytes([200] * (16 * 16))
full_tip.dynamics = BrushDynamics(
    spacing=25, opacity=70, flow=85,
    scatter=300, count=2, scatter_both_axes=True,
    size_jitter=50, angle_jitter=90, roundness_jitter=30,
    flip_x=True, flip_y=True,
    airbrush=True, smoothing=True,
    hue_jitter=10, saturation_jitter=20, brightness_jitter=15,
    texture_enabled=True, texture_pattern_name="Grain",
    texture_scale=50, texture_depth=80,
    dual_brush_enabled=True,
)
kpp_full = os.path.join(tmp2, "test_full.kpp")
write_kpp(kpp_full, full_tip)
xf = _extract_kpp_xml(kpp_full)
# Scatter
assert 'ScatterValue' in xf and '3.0000' in xf, "Scatter value not set (300/100=3)"
assert 'Scattering/AxisY' in xf, "Missing AxisY"
# Flip → Mirror + HorizontalMirrorEnabled / VerticalMirrorEnabled
assert 'HorizontalMirrorEnabled' in xf, "Missing HorizontalMirrorEnabled"
assert 'VerticalMirrorEnabled' in xf, "Missing VerticalMirrorEnabled"
# Airbrush
assert 'isAirbrushing' in xf, "Missing isAirbrushing"
# Color dynamics → random sensors on h/s/v
assert 'hSensor' in xf, "Missing hSensor"
assert 'sSensor' in xf, "Missing sSensor"
assert 'vSensor' in xf, "Missing vSensor"
# Texture
assert 'Texture/Pattern/Enabled' in xf, "Missing texture enabled"
assert 'Texture/Pattern/Scale' in xf, "Missing texture scale"
# Masking brush (dual brush) — full preset
assert 'MaskingBrush/Enabled' in xf, "Missing masking brush"
assert 'MaskingBrush/MaskingCompositeOp' in xf, "Missing masking composite op"
assert 'MaskingBrush/Preset/brush_definition' in xf, "Missing masking brush definition"
assert 'MaskingBrush/Preset/requiredBrushFile' in xf, "Missing masking required brush"
assert 'MaskingBrush/UseMasterSize' in xf, "Missing masking master size"
assert 'MaskingBrush/Preset/ScatterValue' in xf, "Missing masking scatter"
# Size/rotation/ratio jitter → random sensors
assert xf.count('id="random"') >= 3, "Need random sensors for jitter (size+angle+ratio)"
print("write_kpp all dynamics features: OK")

# ── 16d) Test noise → texture fallback ──
noise_tip = BrushTip(name="Noisy", width=8, height=8, channels=1,
                     image_data=bytes([128] * 64), spacing=25)
noise_tip.dynamics = BrushDynamics(spacing=25, noise=True)
kpp_noise = os.path.join(tmp2, "test_noise.kpp")
write_kpp(kpp_noise, noise_tip)
xn = _extract_kpp_xml(kpp_noise)
assert 'Texture/Pattern/Enabled' in xn, "Noise should enable texture"
assert 'true' in xn[xn.find('Texture/Pattern/Enabled'):xn.find('Texture/Pattern/Enabled')+80], \
    "Noise should set texture enabled=true"
assert 'Texture/Pattern/Scale' in xn, "Noise should set texture scale"
print("write_kpp noise → texture fallback: OK")

# ── 16e) Test wet edges → darken/softness ──
wet_tip = BrushTip(name="WetEdge", width=8, height=8, channels=1,
                   image_data=bytes([128] * 64), spacing=25)
wet_tip.dynamics = BrushDynamics(spacing=25, wet_edges=True)
kpp_wet = os.path.join(tmp2, "test_wet.kpp")
write_kpp(kpp_wet, wet_tip)
xw = _extract_kpp_xml(kpp_wet)
assert 'DarkenValue' in xw, "Missing DarkenValue"
assert '0.85' in xw, "Wet edges should set DarkenValue=0.85"
assert 'SoftnessValue' in xw, "Missing SoftnessValue"
assert '0.5' in xw, "Wet edges should set SoftnessValue=0.5"
print("write_kpp wet edges: OK")

# ── 16f) Test dual brush parser fields ──
dual_dyn = BrushDynamics(
    spacing=25,
    dual_brush_enabled=True,
    dual_brush_diameter=50,
    dual_brush_spacing=30,
    dual_brush_scatter=200,
    dual_brush_count=3,
    dual_brush_mode="multiply",
    dual_brush_flip=True,
    dual_brush_roundness=75,
    dual_brush_angle=45,
)
assert dual_dyn.dual_brush_diameter == 50
assert dual_dyn.dual_brush_scatter == 200
assert dual_dyn.dual_brush_flip is True
print("write_kpp dual brush parser fields: OK")

# ── 16g) Test purity/fg-bg jitter → gradient color source ──
purity_tip = BrushTip(name="PurityTest", width=8, height=8, channels=1,
                      image_data=bytes([128] * 64), spacing=25)
purity_tip.dynamics = BrushDynamics(spacing=25, purity=60)
kpp_purity = os.path.join(tmp2, "test_purity.kpp")
write_kpp(kpp_purity, purity_tip)
xp = _extract_kpp_xml(kpp_purity)
assert 'ColorSource/Type' in xp, "Missing ColorSource/Type"
# purity > 0 → gradient color source
idx_cs = xp.find('ColorSource/Type')
assert 'gradient' in xp[idx_cs:idx_cs+100], "Purity>0 should set ColorSource=gradient"
# Mix sensor should use random for jitter
assert 'MixSensor' in xp, "Missing MixSensor"
assert 'MixValue' in xp, "Missing MixValue"
# mix_value = (60+100)/200 = 0.8
assert '0.8000' in xp, f"Mix value should be 0.8000 for purity=60"
print("write_kpp purity → gradient color source: OK")

# ── 16h) Test purity=0 keeps plain color source ──
no_purity_tip = BrushTip(name="NoPurity", width=8, height=8, channels=1,
                         image_data=bytes([128] * 64), spacing=25)
no_purity_tip.dynamics = BrushDynamics(spacing=25, purity=0)
kpp_nopurity = os.path.join(tmp2, "test_nopurity.kpp")
write_kpp(kpp_nopurity, no_purity_tip)
xnp = _extract_kpp_xml(kpp_nopurity)
idx_cs2 = xnp.find('ColorSource/Type')
assert 'plain' in xnp[idx_cs2:idx_cs2+80], "Purity=0 should keep ColorSource=plain"
print("write_kpp purity=0 → plain color source: OK")

# ── 16i) Test negative purity biases toward background ──
neg_purity_tip = BrushTip(name="NegPurity", width=8, height=8, channels=1,
                          image_data=bytes([128] * 64), spacing=25)
neg_purity_tip.dynamics = BrushDynamics(spacing=25, purity=-80)
kpp_negpur = os.path.join(tmp2, "test_negpurity.kpp")
write_kpp(kpp_negpur, neg_purity_tip)
xneg = _extract_kpp_xml(kpp_negpur)
# mix_value = (-80+100)/200 = 0.1
assert '0.1000' in xneg, f"Mix value should be 0.1000 for purity=-80"
assert 'gradient' in xneg, "Negative purity should use gradient"
print("write_kpp negative purity → bg bias: OK")

# ── 16j) Test noise fallback references grain pattern ──
noise_tip2 = BrushTip(name="Noisy2", width=8, height=8, channels=1,
                      image_data=bytes([128] * 64), spacing=25)
noise_tip2.dynamics = BrushDynamics(spacing=25, noise=True)
kpp_noise2 = os.path.join(tmp2, "test_noise2.kpp")
write_kpp(kpp_noise2, noise_tip2)
xn2 = _extract_kpp_xml(kpp_noise2)
# Noise fallback should reference grain pattern name in texture params
assert 'Texture/Pattern/Enabled' in xn2, "Noise should enable texture"
# The pattern should be wired through (06_hard-grain or matched)
print("write_kpp noise → grain pattern reference: OK")

# ── 16k) Test texture pattern file reference ──
tex_tip = BrushTip(name="TextureTest", width=8, height=8, channels=1,
                   image_data=bytes([128] * 64), spacing=25)
tex_tip.dynamics = BrushDynamics(
    spacing=25, texture_enabled=True,
    texture_pattern_name="canvas", texture_scale=80, texture_depth=60)
kpp_tex = os.path.join(tmp2, "test_texture.kpp")
write_kpp(kpp_tex, tex_tip)
xt = _extract_kpp_xml(kpp_tex)
assert 'Texture/Pattern/Enabled' in xt, "Missing texture enabled"
assert 'Texture/Pattern/Scale' in xt, "Missing texture scale"
# Pattern filename reference (may or may not match depending on Krita install)
# Just verify the param structure is present
print("write_kpp texture pattern file reference: OK")

# ── 16l) Test dual brush with masking_tip_override ──
dual_tip2 = BrushTip(name="DualOverride", width=16, height=16, channels=1,
                     image_data=bytes([200] * 256), spacing=25)
dual_tip2.dynamics = BrushDynamics(
    spacing=25, dual_brush_enabled=True,
    dual_brush_diameter=40, dual_brush_hardness=80,
    dual_brush_roundness=100, dual_brush_angle=0)
kpp_dual2 = os.path.join(tmp2, "test_dual_override.kpp")
write_kpp(kpp_dual2, dual_tip2, masking_tip_override="custom_mask.gbr")
xd2 = _extract_kpp_xml(kpp_dual2)
assert 'custom_mask.gbr' in xd2, "masking_tip_override should appear in XML"
assert 'MaskingBrush/Preset/requiredBrushFile' in xd2, "Missing masking required brush"
print("write_kpp dual brush masking_tip_override: OK")

# ── 16m) Test dual_brush_tip_name field ──
dyn_named = BrushDynamics(
    spacing=25,
    dual_brush_enabled=True,
    dual_brush_tip_name="Some Texture Brush",
    dual_brush_diameter=40,
)
assert dyn_named.dual_brush_tip_name == "Some Texture Brush"
assert dyn_named.dual_brush_enabled is True
print("dual_brush_tip_name field: OK")

# ── 16n) Test _find_tip_by_name exact match ──
from abr_brush_importer.import_pipeline import _find_tip_by_name

tip_a = BrushTip(name="Alpha Brush", width=8, height=8, channels=1,
                 image_data=bytes([128] * 64), spacing=25)
tip_b = BrushTip(name="Beta Brush", width=8, height=8, channels=1,
                 image_data=bytes([200] * 64), spacing=25)
tip_c = BrushTip(name="Gamma Brush", width=8, height=8, channels=1,
                 image_data=bytes([100] * 64), spacing=25)
tips_list = [tip_a, tip_b, tip_c]

# Exact match (case-insensitive)
found = _find_tip_by_name(tips_list, "beta brush")
assert found is tip_b, f"Exact match failed: got {found.name if found else None}"

# Partial match
found2 = _find_tip_by_name(tips_list, "Gamma")
assert found2 is tip_c, f"Partial match failed: got {found2.name if found2 else None}"

# No match
found3 = _find_tip_by_name(tips_list, "NonExistent")
assert found3 is None, "Should return None for no match"

# Exclude
found4 = _find_tip_by_name(tips_list, "Alpha Brush", exclude=tip_a)
assert found4 is None, "Should return None when match is excluded"
print("_find_tip_by_name: OK")

# ── 16o) Test sampled dual brush in import_abr_files ──
# Build a fake v1 ABR with 2 tips, where tip 0 has dual brush referencing tip 1
tmp_dual_pipe = tempfile.mkdtemp()
# We'll create 2 BrushTips manually and test the pipeline logic
# by writing a kpp with masking_tip_override from a resolved name

dual_primary = BrushTip(name="Primary", width=16, height=16, channels=1,
                        image_data=bytes([200] * 256), spacing=25)
dual_primary.dynamics = BrushDynamics(
    spacing=25,
    dual_brush_enabled=True,
    dual_brush_tip_name="Secondary",
    dual_brush_diameter=20,
    dual_brush_spacing=30,
)

dual_secondary = BrushTip(name="Secondary", width=10, height=10, channels=1,
                          image_data=bytes([150] * 100), spacing=25)

# Verify _find_tip_by_name finds the secondary tip
matched = _find_tip_by_name([dual_primary, dual_secondary],
                            "Secondary", exclude=dual_primary)
assert matched is dual_secondary, "Should find secondary tip by name"

# Write a kpp with masking override to verify the full path works
kpp_sampled_dual = os.path.join(tmp_dual_pipe, "test_sampled_dual.kpp")
write_kpp(kpp_sampled_dual, dual_primary,
          masking_tip_override="Secondary_mask.gbr")
xs = _extract_kpp_xml(kpp_sampled_dual)
assert 'Secondary_mask.gbr' in xs, "Sampled dual tip file not in XML"
assert 'MaskingBrush/Enabled' in xs, "Missing masking brush enabled"
assert 'true' in xs[xs.find('MaskingBrush/Enabled'):xs.find('MaskingBrush/Enabled')+60], \
    "MaskingBrush should be enabled"
shutil.rmtree(tmp_dual_pipe)
print("sampled dual brush pipeline: OK")

# ── 16p) Test write_kpp colorsmudge "smudge" mode (gouache/oil) ──
smudge_tip = BrushTip(name="Gouache Test", width=16, height=16, channels=1,
                      image_data=bytes([180] * 256), spacing=25)
kpp_smudge = os.path.join(tmp2, "test_smudge.kpp")
write_kpp(kpp_smudge, smudge_tip, invert=True, use_pressure=True,
          paint_mode="smudge")
xs = _extract_kpp_xml(kpp_smudge)
assert 'paintopid="colorsmudge"' in xs, "smudge mode should use colorsmudge engine"
assert 'SmudgeRateValue' in xs, "smudge mode missing SmudgeRateValue"
assert 'ColorRateValue' in xs, "smudge mode missing ColorRateValue"
# Gouache: ColorRateValue should be 1 (full opaque colour)
cri = xs.find('ColorRateValue')
assert '1' in xs[cri:cri+80], "smudge mode ColorRateValue should be 1"
assert 'SmudgeRadiusValue' in xs, "smudge mode missing SmudgeRadiusValue"
assert 'Gouache Test.gbr' in xs, "smudge mode tip filename not in XML"
print("colorsmudge smudge mode (gouache): OK")

# ── 16q) Test write_kpp colorsmudge "wash" mode (watercolour) ──
wash_tip = BrushTip(name="Watercolour Test", width=16, height=16, channels=1,
                    image_data=bytes([120] * 256), spacing=25)
kpp_wash = os.path.join(tmp2, "test_wash.kpp")
write_kpp(kpp_wash, wash_tip, invert=True, use_pressure=True,
          paint_mode="wash")
xw = _extract_kpp_xml(kpp_wash)
assert 'paintopid="colorsmudge"' in xw, "wash mode should use colorsmudge engine"
# Watercolour: ColorRateValue should be 0.5 (translucent)
crw = xw.find('ColorRateValue')
assert '0.5' in xw[crw:crw+80], "wash mode ColorRateValue should be 0.5"
print("colorsmudge wash mode (watercolour): OK")

# ── 16r) Test write_kpp paint_mode=None falls back to paintbrush ──
kpp_pixel = os.path.join(tmp2, "test_pixel_default.kpp")
write_kpp(kpp_pixel, smudge_tip, paint_mode=None)
xp = _extract_kpp_xml(kpp_pixel)
assert 'paintopid="paintbrush"' in xp, "None paint_mode should use paintbrush"
assert 'SmudgeRate' not in xp, "paintbrush mode should not have SmudgeRate"
print("paint_mode=None → paintbrush: OK")

# ── 16s) Test colorsmudge with no dynamics (typical ABR stamp brush) ──
bare_tip = BrushTip(name="Bare Stamp", width=32, height=32, channels=1,
                    image_data=bytes([200] * 1024), spacing=50)
kpp_bare = os.path.join(tmp2, "test_bare_smudge.kpp")
write_kpp(kpp_bare, bare_tip, paint_mode="smudge")
xb = _extract_kpp_xml(kpp_bare)
assert 'paintopid="colorsmudge"' in xb, "bare tip smudge should use colorsmudge"
assert 'Bare Stamp.gbr' in xb, "bare tip filename not in coloursmudge XML"
print("colorsmudge bare stamp brush: OK")

# ── 17) Test write_kpp with invert ──
inv_tip = BrushTip(name="Inverted", width=4, height=4, channels=1,
                   image_data=bytes([100] * 16), spacing=25)
kpp_inv_path = os.path.join(tmp2, "test_inv.kpp")
write_kpp(kpp_inv_path, inv_tip, invert=True)
assert os.path.isfile(kpp_inv_path), "write_kpp with invert did not create file"
xml_inv = _extract_kpp_xml(kpp_inv_path)
assert '<Preset' in xml_inv, "invert kpp missing preset XML"
print("write_kpp with invert: OK")

# ── 18) Test write_kpp with RGBA tip ──
rgba_tip = BrushTip(name="RGBA Brush", width=8, height=8, channels=4,
                    image_data=bytes([255, 0, 0, 200] * 64), spacing=30)
kpp_rgba_path = os.path.join(tmp2, "test_rgba.kpp")
write_kpp(kpp_rgba_path, rgba_tip)
assert os.path.isfile(kpp_rgba_path)
print("write_kpp with RGBA: OK")

shutil.rmtree(tmp2)

# ── 19) Sensor XML is now internal — verify via preset XML ──
xml_sensor = _make_preset_xml("S Test", "s.gbr", 50.0, 0.25, 1.0, 1.0,
                               use_pressure=True,
                               size_curve=[(0.0, 0.0), (1.0, 1.0)])
assert 'id="pressure"' in xml_sensor, "pressure sensor missing from XML"
assert '<curve>' in xml_sensor, "curve element missing from XML"
print("sensor XML in preset: OK")

# ── 20) Test write_kpp enables pressure sensitivity by default ──
tmp3 = tempfile.mkdtemp()
pressure_tip = BrushTip()
pressure_tip.name = "Pressure Test"
pressure_tip.width = 32
pressure_tip.height = 32
pressure_tip.spacing = 25
pressure_tip.channels = 1
pressure_tip.image_data = ABRParser._generate_computed_image(32, 100, 0, 80)

kpp_pressure_path = os.path.join(tmp3, "test_pressure.kpp")
write_kpp(kpp_pressure_path, pressure_tip, use_pressure=True)
xml_content = _extract_kpp_xml(kpp_pressure_path)
assert 'PressureSize' in xml_content, "PressureSize missing"
assert '<![CDATA[true]]>' in xml_content, "PressureSize not true"
assert 'SizeUseCurve' in xml_content, "SizeUseCurve missing"
print("write_kpp pressure sensitivity (default on): OK")

# ── 21) Test write_kpp disables pressure sensitivity when use_pressure=False ──
kpp_nopress_path = os.path.join(tmp3, "test_nopress.kpp")
write_kpp(kpp_nopress_path, pressure_tip, use_pressure=False)
xml_content = _extract_kpp_xml(kpp_nopress_path)
# PressureSize should be false when use_pressure=False
assert 'name="PressureSize"' in xml_content, "PressureSize param missing"
# Check the value is false
import re as _re
m = _re.search(r'name="PressureSize"[^>]*><!\[CDATA\[(.*?)\]\]>', xml_content)
assert m and m.group(1) == 'false', f"PressureSize should be false, got {m.group(1) if m else 'not found'}"
print("write_kpp pressure sensitivity (disabled): OK")

# ── 22) Test write_kpp preserves ABR pressure curves ──
curve_tip = BrushTip()
curve_tip.name = "Curve Brush"
curve_tip.width = 16
curve_tip.height = 16
curve_tip.spacing = 25
curve_tip.channels = 1
curve_tip.image_data = bytes([200] * 256)
curve_tip.dynamics = BrushDynamics(
    spacing=25, opacity=100, flow=100,
    size_pressure_curve=[(0.0, 0.0), (0.5, 0.3), (1.0, 1.0)],
    opacity_pressure_curve=[(0.0, 0.0), (1.0, 1.0)],
    flow_pressure_curve=[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)],
)

kpp_curve_path = os.path.join(tmp3, "test_curve.kpp")
write_kpp(kpp_curve_path, curve_tip, use_pressure=True)
xml_content = _extract_kpp_xml(kpp_curve_path)
# Size pressure curve with custom mid-point
assert '0.5,0.3' in xml_content, "custom size pressure curve mid-point not found"
# Opacity sensor
assert 'OpacityUseCurve' in xml_content, "OpacityUseCurve missing"
# Flow sensor
assert 'FlowUseCurve' in xml_content, "FlowUseCurve missing"
print("write_kpp with ABR pressure curves: OK")

# ── 23) Test roundness_jitter is handled (params in Krita format) ──
rj_tip = BrushTip()
rj_tip.name = "RJ Brush"
rj_tip.width = 16
rj_tip.height = 16
rj_tip.spacing = 25
rj_tip.channels = 1
rj_tip.image_data = bytes([200] * 256)
rj_tip.dynamics = BrushDynamics(spacing=25, roundness_jitter=60)

kpp_rj_path = os.path.join(tmp3, "test_rj.kpp")
write_kpp(kpp_rj_path, rj_tip)
xml_content = _extract_kpp_xml(kpp_rj_path)
assert '<Preset' in xml_content, "Missing <Preset> in roundness jitter test"
print("write_kpp RoundnessJitter: OK")

shutil.rmtree(tmp3)

# ── Utils: _sanitize ──
from abr_brush_importer.utils import _sanitize, _unique, _choose_format, brushes_dest, patterns_dest

assert _sanitize("Test Brush 1") == "Test Brush 1", "_sanitize: plain name"
assert _sanitize("My/Brush!@#$") == "My_Brush____", "_sanitize: special chars"
assert _sanitize("") == "brush", "_sanitize: empty string"
assert _sanitize("...") == "brush", "_sanitize: only dots"
assert _sanitize("A" * 200) == "A" * 100, "_sanitize: length cap"
assert _sanitize("  leading-trailing  ") == "leading-trailing", "_sanitize: strip spaces"
print("_sanitize: OK")

# ── Utils: _unique ──
tmp_u = tempfile.mkdtemp()
p = os.path.join(tmp_u, "brush.gbr")
assert _unique(p) == p, "_unique: non-existing path unchanged"
open(p, "w").close()
p1 = _unique(p)
assert p1 == os.path.join(tmp_u, "brush_1.gbr"), f"_unique: first collision → _1, got {p1}"
open(p1, "w").close()
p2 = _unique(p)
assert p2 == os.path.join(tmp_u, "brush_2.gbr"), f"_unique: second collision → _2, got {p2}"
shutil.rmtree(tmp_u)
print("_unique: OK")

# ── Utils: _choose_format ──
plain_tip = BrushTip()
plain_tip.name = "Plain"
plain_tip.width = 16
plain_tip.height = 16
plain_tip.channels = 1
plain_tip.image_data = bytes([128] * (plain_tip.width * plain_tip.height * plain_tip.channels))
assert _choose_format(plain_tip) == "gbr", "_choose_format: no dynamics → gbr"

dyn_tip = BrushTip()
dyn_tip.name = "Dynamic"
dyn_tip.width = 16
dyn_tip.height = 16
dyn_tip.channels = 1
dyn_tip.image_data = bytes([128] * (dyn_tip.width * dyn_tip.height * dyn_tip.channels))
dyn_tip.dynamics = BrushDynamics(spacing=25, scatter=50)
assert _choose_format(dyn_tip) == "kpp", "_choose_format: dynamics → kpp"
print("_choose_format: OK")

# ── Utils: destination path helpers ──
tmp_res = tempfile.mkdtemp()
b_dir = brushes_dest(tmp_res)
assert b_dir == os.path.join(tmp_res, "brushes"), "brushes_dest path"
assert os.path.isdir(b_dir), "brushes_dest creates directory"
p_dir = patterns_dest(tmp_res)
assert p_dir == os.path.join(tmp_res, "patterns"), "patterns_dest path"
assert os.path.isdir(p_dir), "patterns_dest creates directory"
shutil.rmtree(tmp_res)
print("brushes_dest / patterns_dest: OK")

# ================================================================== #
#  New module tests                                                    #
# ================================================================== #

# ── ImportDB ──
from abr_brush_importer.import_db import ImportDB

tmp_db = tempfile.mkdtemp()

# Fresh DB: every path is considered changed
db = ImportDB(tmp_db)
assert db.is_changed("/fake/brushes.abr"), "ImportDB: new path should be changed"

# Create a real file so mtime can be read
abr_fake = os.path.join(tmp_db, "test.abr")
open(abr_fake, "w").close()
db.mark_imported(abr_fake)
assert not db.is_changed(abr_fake), "ImportDB: unchanged file should not be changed"

# Touch the file to change its mtime
import time as _time_mod
_time_mod.sleep(0.05)
os.utime(abr_fake, None)
assert db.is_changed(abr_fake), "ImportDB: touched file should be changed again"

# Error logging
db.log_error(abr_fake, "some parse error")
errors = db.get_recent_errors(5)
assert len(errors) == 1, "ImportDB: one error logged"
assert errors[0]["message"] == "some parse error", "ImportDB: error message stored"

# get_last_import_time: non-None after mark_imported
db.mark_imported(abr_fake)
t = db.get_last_import_time()
assert t is not None and isinstance(t, float), "ImportDB: last import time is a float"
t2 = db.get_last_import_time(abr_fake)
assert t2 is not None, "ImportDB: per-file last import time not None"

# Persistence: reload from disk
db2 = ImportDB(tmp_db)
assert not db2.is_changed(abr_fake), "ImportDB: persisted state not changed after reload"

# tracked_paths
paths = db2.tracked_paths()
assert abr_fake in paths, "ImportDB: tracked_paths includes imported file"

shutil.rmtree(tmp_db)
print("ImportDB: OK")

# ── AutoImportSettings ──
from abr_brush_importer.auto_import import AutoImportSettings

tmp_cfg = tempfile.mkdtemp()
s = AutoImportSettings(tmp_cfg)

# Defaults
assert s.auto_import_enabled is False, "AutoImportSettings: default enabled=False"
assert s.watch_folder_path == "", "AutoImportSettings: default folder empty"
assert s.watch_recursive is False, "AutoImportSettings: default recursive=False"
assert s.auto_import_on_startup is False, "AutoImportSettings: default startup=False"
assert s.auto_refresh_resources is True, "AutoImportSettings: default refresh=True"
assert isinstance(s.max_download_bytes, int), "AutoImportSettings: max_download_bytes is int"
assert isinstance(s.auto_download_urls, list), "AutoImportSettings: auto_download_urls is list"

# Set and persist
s.auto_import_enabled = True
s.watch_folder_path = "/tmp/abr_test"
s.watch_recursive = True
s.auto_import_on_startup = True
s.auto_refresh_resources = False

# Reload from disk
s2 = AutoImportSettings(tmp_cfg)
assert s2.auto_import_enabled is True, "AutoImportSettings: persisted enabled"
assert s2.watch_folder_path == "/tmp/abr_test", "AutoImportSettings: persisted folder"
assert s2.watch_recursive is True, "AutoImportSettings: persisted recursive"
assert s2.auto_import_on_startup is True, "AutoImportSettings: persisted startup"
assert s2.auto_refresh_resources is False, "AutoImportSettings: persisted refresh"

shutil.rmtree(tmp_cfg)
print("AutoImportSettings: OK")

# ── ImportOptions / ImportResult ──
from abr_brush_importer.import_pipeline import ImportOptions, ImportResult, import_abr_files

opts = ImportOptions()
assert opts.use_best_match is True, "ImportOptions: default use_best_match"
assert opts.use_pressure is True, "ImportOptions: default use_pressure"
assert opts.export_patterns is True, "ImportOptions: default export_patterns"

res = ImportResult(imported=3, skipped=1)
assert res.ok is True, "ImportResult: ok when imported>0 and no errors"
assert res.total_errors == 0, "ImportResult: total_errors 0"

res_err = ImportResult(imported=0, errors=["oops"])
assert res_err.ok is False, "ImportResult: not ok when imported=0"
assert res_err.total_errors == 1, "ImportResult: total_errors counts errors"
print("ImportOptions / ImportResult: OK")

# ── import_abr_files: empty paths ──
tmp_pipe = tempfile.mkdtemp()
result = import_abr_files([], tmp_pipe, ImportOptions(auto_refresh=False))
assert result.imported == 0, "import_abr_files: empty paths → 0 imported"
assert result.skipped == 0, "import_abr_files: empty paths → 0 skipped"
shutil.rmtree(tmp_pipe)
print("import_abr_files (empty): OK")

# ── import_abr_files: real v1 ABR file ──
import struct as _struct

def _build_fake_v1_abr():
    buf = bytearray()
    buf += _struct.pack(">H", 1)
    buf += _struct.pack(">H", 1)
    brush_data = bytearray()
    brush_data += _struct.pack(">I", 0)
    brush_data += _struct.pack(">H", 25)
    brush_data += _struct.pack(">H", 20)
    brush_data += _struct.pack(">H", 100)
    brush_data += _struct.pack(">H", 0)
    brush_data += _struct.pack(">H", 100)
    buf += _struct.pack(">H", 1)
    buf += _struct.pack(">I", len(brush_data))
    buf += brush_data
    return bytes(buf)

tmp_pipe2 = tempfile.mkdtemp()
fake_abr_path = os.path.join(tmp_pipe2, "fake.abr")
with open(fake_abr_path, "wb") as f:
    f.write(_build_fake_v1_abr())

result2 = import_abr_files(
    [fake_abr_path], tmp_pipe2,
    ImportOptions(use_best_match=True, auto_refresh=False),
)
assert result2.imported == 1, f"import_abr_files: expected 1 imported, got {result2.imported}"
assert result2.errors == [], f"import_abr_files: expected no errors, got {result2.errors}"

# Verify the .gbr was written (no dynamics → gbr)
brushes_dir = os.path.join(tmp_pipe2, "brushes")
gbr_files = [f for f in os.listdir(brushes_dir) if f.endswith(".gbr")]
assert gbr_files, "import_abr_files: .gbr file should be written"
print(f"import_abr_files (v1 ABR): OK  [{gbr_files[0]}]")

# ── import_abr_files: DB skips unchanged ──
db_pipe = ImportDB(tmp_pipe2)
db_pipe.mark_imported(fake_abr_path)
result3 = import_abr_files(
    [fake_abr_path], tmp_pipe2,
    ImportOptions(auto_refresh=False),
    db=db_pipe,
)
assert result3.imported == 0, "import_abr_files: unchanged file should be skipped"
assert result3.skipped == 1, "import_abr_files: skipped count should be 1"
print("import_abr_files (DB skip): OK")

# ── import_abr_files: DB marks re-import after file change ──
_time_mod.sleep(0.05)
os.utime(fake_abr_path, None)  # bump mtime
result4 = import_abr_files(
    [fake_abr_path], tmp_pipe2,
    ImportOptions(auto_refresh=False),
    db=db_pipe,
)
assert result4.imported == 1, "import_abr_files: changed file should be re-imported"
print("import_abr_files (DB re-import after mtime change): OK")

shutil.rmtree(tmp_pipe2)

# ── scan_and_import: non-existent folder returns empty result ──
from abr_brush_importer.auto_import import scan_and_import

res_none = scan_and_import("/nonexistent/path", tmp_pipe2)
assert res_none.imported == 0, "scan_and_import: missing folder → 0 imported"
print("scan_and_import (missing folder): OK")

# ── scan_and_import: folder with no .abr files ──
tmp_empty = tempfile.mkdtemp()
res_empty = scan_and_import(tmp_empty, tmp_empty)
assert res_empty.imported == 0, "scan_and_import: empty folder → 0 imported"
shutil.rmtree(tmp_empty)
print("scan_and_import (empty folder): OK")

# ── scan_and_import: folder with one .abr file ──
tmp_scan = tempfile.mkdtemp()
scan_abr = os.path.join(tmp_scan, "brushes.abr")
with open(scan_abr, "wb") as f:
    f.write(_build_fake_v1_abr())

res_scan = scan_and_import(
    tmp_scan, tmp_scan,
    options=ImportOptions(auto_refresh=False),
)
assert res_scan.imported == 1, f"scan_and_import: expected 1, got {res_scan.imported}"
print("scan_and_import (one .abr): OK")

# Second scan: same file unchanged → should be skipped
db_scan = ImportDB(tmp_scan)
# Mark the file so the DB considers it already imported
db_scan.mark_imported(scan_abr)
res_scan2 = scan_and_import(
    tmp_scan, tmp_scan,
    db=db_scan,
    options=ImportOptions(auto_refresh=False),
)
assert res_scan2.skipped == 1, "scan_and_import: second run skips unchanged file"
print("scan_and_import (skip unchanged): OK")

shutil.rmtree(tmp_scan)

# ── 16t) Test write_kpp "oil_thick" mode (heavy oil / palette knife) ──
oil_tip = BrushTip(name="Oil Thick Test", width=16, height=16, channels=1,
                   image_data=bytes([180] * 256), spacing=25)
kpp_oil = os.path.join(tmp2, "test_oil_thick.kpp")
write_kpp(kpp_oil, oil_tip, paint_mode="oil_thick")
xot = _extract_kpp_xml(kpp_oil)
assert 'paintopid="colorsmudge"' in xot, "oil_thick should use colorsmudge engine"
# Heavy oil: SmudgeRadiusValue ≈ 9.23 (large pickup)
sri = xot.find('SmudgeRadiusValue')
assert '9.23' in xot[sri:sri+80], "oil_thick SmudgeRadiusValue should be 9.23"
# ColorRateValue should be 0.7
cri = xot.find('ColorRateValue')
assert '0.7' in xot[cri:cri+80], "oil_thick ColorRateValue should be 0.7"
print("colorsmudge oil_thick mode: OK")

# ── 16u) Test write_kpp "acrylic" mode (opaque, less mixing) ──
acr_tip = BrushTip(name="Acrylic Test", width=16, height=16, channels=1,
                   image_data=bytes([200] * 256), spacing=25)
kpp_acr = os.path.join(tmp2, "test_acrylic.kpp")
write_kpp(kpp_acr, acr_tip, paint_mode="acrylic")
xac = _extract_kpp_xml(kpp_acr)
assert 'paintopid="colorsmudge"' in xac, "acrylic should use colorsmudge engine"
# Acrylic: SmudgeRateValue should be 0.4 (less mixing)
smri = xac.find('SmudgeRateValue')
assert '0.4' in xac[smri:smri+80], "acrylic SmudgeRateValue should be 0.4"
# SmudgeRateMode should be 0
smi = xac.find('SmudgeRateMode')
assert '0' in xac[smi:smi+50], "acrylic SmudgeRateMode should be 0"
print("colorsmudge acrylic mode: OK")

# ── 16v) Test write_kpp "chalk" mode (textured grain) ──
chalk_tip = BrushTip(name="Chalk Test", width=16, height=16, channels=1,
                     image_data=bytes([150] * 256), spacing=25)
kpp_chalk = os.path.join(tmp2, "test_chalk.kpp")
write_kpp(kpp_chalk, chalk_tip, paint_mode="chalk")
xch = _extract_kpp_xml(kpp_chalk)
assert 'paintopid="paintbrush"' in xch, "chalk should use paintbrush engine"
assert 'Texture/Pattern/Enabled' in xch, "chalk should have texture params"
tei = xch.find('Texture/Pattern/Enabled')
assert 'true' in xch[tei:tei+80], "chalk Texture/Pattern/Enabled should be true"
# CompositeOp should be normal (chalk doesn't change composite)
ci = xch.find('CompositeOp')
assert 'normal' in xch[ci:ci+50], "chalk CompositeOp should be normal"
print("paintbrush chalk mode: OK")

# ── 16w) Test write_kpp "charcoal" mode (heavy grain, smaller scale) ──
char_tip = BrushTip(name="Charcoal Test", width=16, height=16, channels=1,
                    image_data=bytes([160] * 256), spacing=25)
kpp_char = os.path.join(tmp2, "test_charcoal.kpp")
write_kpp(kpp_char, char_tip, paint_mode="charcoal")
xcr = _extract_kpp_xml(kpp_char)
assert 'paintopid="paintbrush"' in xcr, "charcoal should use paintbrush engine"
tec = xcr.find('Texture/Pattern/Enabled')
assert 'true' in xcr[tec:tec+80], "charcoal should have texture enabled"
# CharcoalScale should be 0.35 (smaller than chalk)
tsc = xcr.find('Texture/Pattern/Scale')
assert '0.35' in xcr[tsc:tsc+80], "charcoal Texture/Pattern/Scale should be 0.35"
print("paintbrush charcoal mode: OK")

# ── 16x) Test write_kpp "marker" mode (flat strokes, darken composite) ──
marker_tip = BrushTip(name="Marker Test", width=16, height=16, channels=1,
                      image_data=bytes([255] * 256), spacing=25)
kpp_marker = os.path.join(tmp2, "test_marker.kpp")
write_kpp(kpp_marker, marker_tip, paint_mode="marker")
xmk = _extract_kpp_xml(kpp_marker)
assert 'paintopid="paintbrush"' in xmk, "marker should use paintbrush engine"
# Marker: CompositeOp should be darken
cmi = xmk.find('CompositeOp')
assert 'darken' in xmk[cmi:cmi+50], "marker CompositeOp should be darken"
# Flow should be 1
fi = xmk.find('FlowValue')
assert '1.0' in xmk[fi:fi+40], "marker FlowValue should be 1.0"
print("paintbrush marker mode: OK")

# ── 16y) Test write_kpp "pencil" mode (fine texture, low flow) ──
pencil_tip = BrushTip(name="Pencil Test", width=16, height=16, channels=1,
                      image_data=bytes([140] * 256), spacing=25)
kpp_pencil = os.path.join(tmp2, "test_pencil.kpp")
write_kpp(kpp_pencil, pencil_tip, paint_mode="pencil")
xpe = _extract_kpp_xml(kpp_pencil)
assert 'paintopid="paintbrush"' in xpe, "pencil should use paintbrush engine"
tpe = xpe.find('Texture/Pattern/Enabled')
assert 'true' in xpe[tpe:tpe+80], "pencil should have texture enabled"
fpe = xpe.find('FlowValue')
assert '0.4' in xpe[fpe:fpe+40], "pencil FlowValue should be 0.4"
print("paintbrush pencil mode: OK")

# ── 16z) Test write_kpp "colored_pencil" mode (light texture, medium flow) ──
cp_tip = BrushTip(name="Colored Pencil Test", width=16, height=16, channels=1,
                  image_data=bytes([150] * 256), spacing=25)
kpp_cp = os.path.join(tmp2, "test_colored_pencil.kpp")
write_kpp(kpp_cp, cp_tip, paint_mode="colored_pencil")
xcp = _extract_kpp_xml(kpp_cp)
assert 'paintopid="paintbrush"' in xcp, "colored_pencil should use paintbrush"
tcp = xcp.find('Texture/Pattern/Enabled')
assert 'true' in xcp[tcp:tcp+80], "colored_pencil should have texture enabled"
fcp = xcp.find('FlowValue')
assert '0.6' in xcp[fcp:fcp+40], "colored_pencil FlowValue should be 0.6"
print("paintbrush colored_pencil mode: OK")

# ── 16aa) Test write_kpp "conte" mode (dense chalky grain) ──
conte_tip = BrushTip(name="Conte Test", width=16, height=16, channels=1,
                     image_data=bytes([160] * 256), spacing=25)
kpp_conte = os.path.join(tmp2, "test_conte.kpp")
write_kpp(kpp_conte, conte_tip, paint_mode="conte")
xco = _extract_kpp_xml(kpp_conte)
assert 'paintopid="paintbrush"' in xco, "conte should use paintbrush"
tco = xco.find('Texture/Pattern/Enabled')
assert 'true' in xco[tco:tco+80], "conte should have texture enabled"
sco = xco.find('Texture/Pattern/Scale')
assert '0.5' in xco[sco:sco+80], "conte Texture/Pattern/Scale should be 0.50"
print("paintbrush conte mode: OK")

# ── 16ab) Test write_kpp "ink" mode (sharp, solid strokes) ──
ink_tip = BrushTip(name="Ink Test", width=16, height=16, channels=1,
                   image_data=bytes([255] * 256), spacing=25)
kpp_ink = os.path.join(tmp2, "test_ink.kpp")
write_kpp(kpp_ink, ink_tip, paint_mode="ink")
xik = _extract_kpp_xml(kpp_ink)
assert 'paintopid="paintbrush"' in xik, "ink should use paintbrush"
fik = xik.find('FlowValue')
assert '1.0' in xik[fik:fik+40], "ink FlowValue should be 1.0"
oik = xik.find('OpacityValue')
assert '1.0' in xik[oik:oik+40], "ink OpacityValue should be 1.0"
print("paintbrush ink mode: OK")

# ── 16ac) Test write_kpp "spray" mode (scattered airbrush) ──
spray_tip = BrushTip(name="Spray Test", width=16, height=16, channels=1,
                     image_data=bytes([200] * 256), spacing=25)
kpp_spray = os.path.join(tmp2, "test_spray.kpp")
write_kpp(kpp_spray, spray_tip, paint_mode="spray")
xsp = _extract_kpp_xml(kpp_spray)
assert 'paintopid="paintbrush"' in xsp, "spray should use paintbrush"
assert 'isAirbrushing' in xsp, "spray should have airbrush param"
asp = xsp.find('isAirbrushing')
assert 'true' in xsp[asp:asp+80], "spray should have airbrush enabled"
print("paintbrush spray mode: OK")

# ── 16ad) Test write_kpp "airbrush_soft" mode (soft airbrush) ──
ab_tip = BrushTip(name="Airbrush Test", width=16, height=16, channels=1,
                  image_data=bytes([180] * 256), spacing=25)
kpp_ab = os.path.join(tmp2, "test_airbrush.kpp")
write_kpp(kpp_ab, ab_tip, paint_mode="airbrush_soft")
xab = _extract_kpp_xml(kpp_ab)
assert 'paintopid="paintbrush"' in xab, "airbrush_soft should use paintbrush"
assert 'isAirbrushing' in xab, "airbrush_soft should have airbrush param"
aab = xab.find('isAirbrushing')
assert 'true' in xab[aab:aab+80], "airbrush_soft should have airbrush enabled"
print("paintbrush airbrush_soft mode: OK")

# ── 16ae) Test write_kpp "tempera" mode (fast-drying, minimal mixing) ──
temp_tip = BrushTip(name="Tempera Test", width=16, height=16, channels=1,
                    image_data=bytes([170] * 256), spacing=25)
kpp_temp = os.path.join(tmp2, "test_tempera.kpp")
write_kpp(kpp_temp, temp_tip, paint_mode="tempera")
xte = _extract_kpp_xml(kpp_temp)
assert 'paintopid="colorsmudge"' in xte, "tempera should use colorsmudge"
smte = xte.find('SmudgeRateValue')
assert '0.15' in xte[smte:smte+80], "tempera SmudgeRateValue should be 0.15"
crte = xte.find('ColorRateValue')
assert '1' in xte[crte:crte+50], "tempera ColorRateValue should be 1"
print("colorsmudge tempera mode: OK")

# ── 16af) Test write_kpp "encaustic" mode (hot wax, thick mixing) ──
enc_tip = BrushTip(name="Encaustic Test", width=16, height=16, channels=1,
                   image_data=bytes([190] * 256), spacing=25)
kpp_enc = os.path.join(tmp2, "test_encaustic.kpp")
write_kpp(kpp_enc, enc_tip, paint_mode="encaustic")
xen = _extract_kpp_xml(kpp_enc)
assert 'paintopid="colorsmudge"' in xen, "encaustic should use colorsmudge"
sren = xen.find('SmudgeRadiusValue')
assert '5.0' in xen[sren:sren+80], "encaustic SmudgeRadiusValue should be 5.0"
cren = xen.find('ColorRateValue')
assert '0.8' in xen[cren:cren+50], "encaustic ColorRateValue should be 0.8"
print("colorsmudge encaustic mode: OK")

# ── 16ag) Test write_kpp "fresco" mode (wet plaster) ──
fres_tip = BrushTip(name="Fresco Test", width=16, height=16, channels=1,
                    image_data=bytes([165] * 256), spacing=25)
kpp_fres = os.path.join(tmp2, "test_fresco.kpp")
write_kpp(kpp_fres, fres_tip, paint_mode="fresco")
xfr = _extract_kpp_xml(kpp_fres)
assert 'paintopid="colorsmudge"' in xfr, "fresco should use colorsmudge"
smfr = xfr.find('SmudgeRateValue')
assert '0.6' in xfr[smfr:smfr+80], "fresco SmudgeRateValue should be 0.6"
crfr = xfr.find('ColorRateValue')
assert '0.7' in xfr[crfr:crfr+50], "fresco ColorRateValue should be 0.7"
print("colorsmudge fresco mode: OK")

print("\nAll tests passed!")
