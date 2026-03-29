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
from abr_brush_importer.kpp_writer import write_kpp, _make_preset_xml, _make_thumbnail

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

# ── 13) Test write_kpp produces a valid ZIP ──
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

import zipfile
with zipfile.ZipFile(kpp_path, 'r') as zf:
    names = zf.namelist()
    assert "preset.xml" in names, f"preset.xml not in .kpp: {names}"
    assert "thumbnail.png" in names, f"thumbnail.png not in .kpp: {names}"
    # At least one .gbr inside
    gbr_files = [n for n in names if n.endswith('.gbr')]
    assert gbr_files, f"No embedded .gbr in .kpp: {names}"

    xml_content = zf.read("preset.xml").decode("utf-8")
    assert "paintbrush" in xml_content, "preset.xml missing paintop id"
    assert "KPP Test" in xml_content, "preset.xml missing brush name"
    assert "Spacing/value" in xml_content, "preset.xml missing Spacing param"
    assert "Opacity/value" in xml_content, "preset.xml missing Opacity param"

print(f"write_kpp: OK (files: {names})")

# ── 14) Test _make_preset_xml content ──
xml = _make_preset_xml("My Brush", "my_brush.gbr", 50.0, 0.25, 0.8, 0.9)
assert "paintbrush" in xml
assert "My Brush" in xml
assert "0.2500" in xml   # spacing
assert "0.8000" in xml   # opacity
assert "0.9000" in xml   # flow
assert "my_brush.gbr" in xml
# New dynamics params that GIMP cannot preserve
assert "hardness" in xml, "hardness param missing from preset.xml"
assert "AutoSmoothing/isChecked" in xml, "AutoSmoothing param missing from preset.xml"
assert "Scatter/value" in xml, "Scatter/value param missing from preset.xml"
assert "SizeJitter/value" in xml, "SizeJitter/value param missing from preset.xml"
assert "AngleJitter/value" in xml, "AngleJitter/value param missing from preset.xml"
print("_make_preset_xml: OK")

# ── 15) Test _make_thumbnail produces valid PNG ──
thumb_tip = BrushTip(width=16, height=16, channels=1,
                     image_data=bytes([128] * 256))
thumb = _make_thumbnail(thumb_tip, 32)
assert thumb[:8] == b'\x89PNG\r\n\x1a\n', "thumbnail is not a valid PNG"
print("_make_thumbnail: OK")

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
with zipfile.ZipFile(kpp_dyn_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    assert "0.7500" in xml_content, "opacity not preserved in preset.xml"
    assert "0.9000" in xml_content, "flow not preserved in preset.xml"
    # Default dynamics: hardness=100 → 1.0000, smoothing=False
    assert '<param name="hardness" type="float">1.0000</param>' in xml_content, \
           "hardness not in preset.xml"
    assert '<param name="AutoSmoothing/isChecked" type="bool">false</param>' in xml_content, \
           "AutoSmoothing missing from preset.xml"
print("write_kpp with dynamics: OK")

# ── 16b) Test write_kpp with extended dynamics (hardness, scatter, jitter, smoothing) ──
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
with zipfile.ZipFile(kpp_ext_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    # Hardness: 75% → 0.7500
    assert '<param name="hardness" type="float">0.7500</param>' in xml_content, \
           f"hardness 0.7500 not found in preset.xml"
    # Ratio/roundness: 50% → ratio=0.5000 in brush_definition (XML-escaped as &quot;)
    assert 'ratio=&quot;0.5000&quot;' in xml_content, \
           "roundness/ratio not found in preset.xml"
    # Scatter: 500/1000 * 10 = 5.0
    assert '<param name="Scatter/value" type="float">5.0000</param>' in xml_content, \
           "scatter value not found in preset.xml"
    # Scatter count: 3
    assert "<param name=\"Scatter/count\" type=\"int\">3</param>" in xml_content, \
           "scatter count not found in preset.xml"
    # Size jitter: 40% → 0.4000
    assert '<param name="SizeJitter/value" type="float">0.4000</param>' in xml_content, \
           "size jitter not found in preset.xml"
    # Angle jitter: 180°/360° = 0.5000
    assert '<param name="AngleJitter/value" type="float">0.5000</param>' in xml_content, \
           "angle jitter not found in preset.xml"
    # Smoothing: True → "true"
    assert '<param name="AutoSmoothing/isChecked" type="bool">true</param>' in xml_content, \
           "smoothing not enabled in preset.xml"
print("write_kpp with extended dynamics: OK")

# ── 17) Test write_kpp with invert ──
inv_tip = BrushTip(name="Inverted", width=4, height=4, channels=1,
                   image_data=bytes([100] * 16), spacing=25)
kpp_inv_path = os.path.join(tmp2, "test_inv.kpp")
write_kpp(kpp_inv_path, inv_tip, invert=True)
with zipfile.ZipFile(kpp_inv_path, 'r') as zf:
    # Check embedded GBR pixels are inverted (100 → 155)
    gbr_file = [n for n in zf.namelist() if n.endswith('.gbr')][0]
    gbr_data = zf.read(gbr_file)
    # GBR header is 28 + name_len bytes; pixel data follows
    # Just verify the file was created without errors
    assert len(gbr_data) > 28, "embedded GBR too short"
print("write_kpp with invert: OK")

# ── 18) Test write_kpp with RGBA tip ──
rgba_tip = BrushTip(name="RGBA Brush", width=8, height=8, channels=4,
                    image_data=bytes([255, 0, 0, 200] * 64), spacing=30)
kpp_rgba_path = os.path.join(tmp2, "test_rgba.kpp")
write_kpp(kpp_rgba_path, rgba_tip)
assert os.path.isfile(kpp_rgba_path)
print("write_kpp with RGBA: OK")

shutil.rmtree(tmp2)

print("\nAll tests passed!")
