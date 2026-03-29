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

from abr_brush_importer.abr_parser import ABRParser, BrushTip, parse_abr
from abr_brush_importer.gbr_writer import write_gbr, write_png

print("All modules import OK")

# 1) Generate a computed brush
tip = BrushTip()
tip.name = "Test Round"
tip.width = 32
tip.height = 32
tip.spacing = 25
tip.image_data = ABRParser._generate_computed_image(32, 100, 0, 80)
print(f"Generated computed brush: {len(tip.image_data)} bytes ({tip.width}x{tip.height})")
assert len(tip.image_data) == 32 * 32

# 2) Write GBR and PNG
tmp = tempfile.mkdtemp()
gbr_path = os.path.join(tmp, "test.gbr")
png_path = os.path.join(tmp, "test.png")
write_gbr(gbr_path, "Test", 32, 32, tip.image_data, 25)
write_png(png_path, 32, 32, tip.image_data)
print(f"GBR: {os.path.getsize(gbr_path)} bytes  |  PNG: {os.path.getsize(png_path)} bytes")

# 3) Verify GBR header
with open(gbr_path, "rb") as f:
    hs, ver, w, h, bpp = struct.unpack(">IIIII", f.read(20))
    magic = f.read(4)
    spacing = struct.unpack(">I", f.read(4))[0]
    print(f"GBR header: v{ver} {w}x{h} bpp={bpp} magic={magic} spacing={spacing}%")
    assert magic == b"GIMP"
    assert ver == 2
    assert w == 32 and h == 32

# 4) Test PackBits decoder
data = bytes([0x02, 0xAA, 0xBB, 0xCC, 0xFE, 0xDD])
result = ABRParser._decode_packbits(data, 6)
assert result == b"\xAA\xBB\xCC\xDD\xDD\xDD", f"PackBits failed: {result.hex()}"
print("PackBits RLE decoder: OK")

# 5) Test round-trip: build a fake v1 ABR in memory, parse it
def build_fake_v1_abr():
    """Create a minimal v1 ABR with one computed brush."""
    buf = bytearray()
    buf += struct.pack(">H", 1)       # version 1
    buf += struct.pack(">H", 1)       # count = 1
    # Brush type 1 (computed)
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
assert tips[0].width == 20
assert tips[0].height == 20
print(f"v1 ABR round-trip: OK (parsed {tips[0].name} {tips[0].width}x{tips[0].height})")

# Cleanup
shutil.rmtree(tmp)

print("\nAll tests passed!")
