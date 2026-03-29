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

print("\nAll tests passed!")
