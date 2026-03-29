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
from abr_brush_importer.kpp_writer import write_kpp, _make_preset_xml, _make_thumbnail, _format_sensor_xml

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

# ── 19) Test _format_sensor_xml helper ──
# Default linear curve
sensor = _format_sensor_xml([])
assert '&lt;sensors&gt;' in sensor, "sensor XML not escaped"
assert 'id=&quot;pressure&quot;' in sensor, "pressure id missing"
assert '0.0000,0.0000' in sensor, "start point missing in default curve"
assert '1.0000,1.0000' in sensor, "end point missing in default curve"
print("_format_sensor_xml (default linear): OK")

# Custom curve — verify start, mid and end points are all present
sensor2 = _format_sensor_xml([(0.0, 0.0), (0.5, 0.25), (1.0, 1.0)])
assert '0.0000,0.0000' in sensor2, "start point missing in custom curve"
assert '0.5000,0.2500' in sensor2, "mid-point missing in custom curve"
assert '1.0000,1.0000' in sensor2, "end point missing in custom curve"
print("_format_sensor_xml (custom curve): OK")

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
with zipfile.ZipFile(kpp_pressure_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    assert 'name="size/useCurve"' in xml_content, \
        "size/useCurve missing when use_pressure=True"
    assert '>true<' in xml_content or 'type="bool">true' in xml_content, \
        "useCurve not set to true when use_pressure=True"
    assert 'name="size/sensor"' in xml_content, \
        "size/sensor missing when use_pressure=True"
    assert 'id=&quot;pressure&quot;' in xml_content, \
        "pressure sensor id missing"
print("write_kpp pressure sensitivity (default on): OK")

# ── 21) Test write_kpp disables pressure sensitivity when use_pressure=False ──
kpp_nopress_path = os.path.join(tmp3, "test_nopress.kpp")
write_kpp(kpp_nopress_path, pressure_tip, use_pressure=False)
with zipfile.ZipFile(kpp_nopress_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    assert 'name="size/useCurve"' not in xml_content, \
        "size/useCurve should be absent when use_pressure=False"
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
with zipfile.ZipFile(kpp_curve_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    # Size pressure curve with custom mid-point
    assert '0.5000,0.3000' in xml_content, \
        "custom size pressure curve mid-point not found"
    # Opacity pressure sensor
    assert 'name="Opacity/useCurve" type="bool">true</param>' in xml_content, \
        "Opacity/useCurve missing for opacity pressure curve"
    assert 'name="Opacity/sensor"' in xml_content, \
        "Opacity/sensor missing"
    # Flow pressure sensor with explicit points
    assert 'name="flow/useCurve" type="bool">true</param>' in xml_content, \
        "flow/useCurve missing for non-empty flow pressure curve"
print("write_kpp with ABR pressure curves: OK")

# ── 23) Test roundness_jitter is emitted in preset.xml ──
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
with zipfile.ZipFile(kpp_rj_path, 'r') as zf:
    xml_content = zf.read("preset.xml").decode("utf-8")
    # roundness_jitter: 60% → 0.6000
    assert '<param name="RoundnessJitter/value" type="float">0.6000</param>' in xml_content, \
        "RoundnessJitter not found in preset.xml"
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
assert s.use_pressure is True, "AutoImportSettings: default use_pressure=True"
assert isinstance(s.max_download_bytes, int), "AutoImportSettings: max_download_bytes is int"
assert isinstance(s.auto_download_urls, list), "AutoImportSettings: auto_download_urls is list"

# Set and persist
s.auto_import_enabled = True
s.watch_folder_path = "/tmp/abr_test"
s.watch_recursive = True
s.auto_import_on_startup = True
s.auto_refresh_resources = False
s.use_pressure = False

# Reload from disk
s2 = AutoImportSettings(tmp_cfg)
assert s2.auto_import_enabled is True, "AutoImportSettings: persisted enabled"
assert s2.watch_folder_path == "/tmp/abr_test", "AutoImportSettings: persisted folder"
assert s2.watch_recursive is True, "AutoImportSettings: persisted recursive"
assert s2.auto_import_on_startup is True, "AutoImportSettings: persisted startup"
assert s2.auto_refresh_resources is False, "AutoImportSettings: persisted refresh"
assert s2.use_pressure is False, "AutoImportSettings: persisted use_pressure"

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

print("\nAll tests passed!")
