"""
ABR (Adobe Brush) file format parser.

Supports ABR versions 1, 2, and 6+ (including v6, v7, v9, v10).
The ABR format stores Photoshop brush tips as grayscale images with
optional metadata like spacing, angle, roundness, and hardness.

Format overview:
  v1/v2: Sequential brush records with type (computed/sampled), dimensions, pixel data.
  v6+:   8BIM resource blocks. 'samp' blocks contain sampled brush images.
         May have 'desc' blocks with brush engine descriptors.
"""

import struct
import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class BrushTip:
    """A single brush tip extracted from an ABR file."""
    name: str = ""
    width: int = 0
    height: int = 0
    depth: int = 8          # bits per channel
    image_data: bytes = b"" # raw grayscale pixel data (1 byte per pixel, 8-bit)
    spacing: int = 25       # percentage (1-1000)
    diameter: int = 0
    angle: int = 0
    roundness: int = 100
    hardness: int = 100
    brush_type: int = 2     # 1=computed, 2=sampled


class ABRParser:
    """Parser for Adobe Brush (.abr) files.

    Usage:
        parser = ABRParser(filepath="brushes.abr")
        tips = parser.parse()
        for tip in tips:
            print(tip.name, tip.width, tip.height)
    """

    def __init__(self, filepath: str = None, data: bytes = None):
        if filepath:
            with open(filepath, 'rb') as f:
                self._data = f.read()
        elif data:
            self._data = data
        else:
            raise ValueError("Either filepath or data must be provided")

        self._stream = io.BytesIO(self._data)
        self.version = 0
        self.subversion = 0

    def parse(self) -> List[BrushTip]:
        """Parse the ABR data and return a list of BrushTip objects."""
        self._stream.seek(0)
        self.version = self._read_uint16()

        if self.version in (1, 2):
            return self._parse_v1_v2()
        elif self.version >= 6:
            self.subversion = self._read_uint16()
            return self._parse_v6_plus()
        else:
            raise ValueError(f"Unsupported ABR version: {self.version}")

    # ------------------------------------------------------------------ #
    #  Binary reading helpers                                              #
    # ------------------------------------------------------------------ #

    def _read(self, n: int) -> bytes:
        data = self._stream.read(n)
        if len(data) < n:
            raise EOFError(f"Expected {n} bytes, got {len(data)}")
        return data

    def _read_uint8(self) -> int:
        return struct.unpack('>B', self._read(1))[0]

    def _read_uint16(self) -> int:
        return struct.unpack('>H', self._read(2))[0]

    def _read_int16(self) -> int:
        return struct.unpack('>h', self._read(2))[0]

    def _read_uint32(self) -> int:
        return struct.unpack('>I', self._read(4))[0]

    def _read_utf16_string(self, char_count: int) -> str:
        raw = self._read(char_count * 2)
        return raw.decode('utf-16-be', errors='replace').rstrip('\x00')

    def _tell(self) -> int:
        return self._stream.tell()

    def _seek(self, pos: int) -> None:
        self._stream.seek(pos)

    def _remaining(self) -> int:
        pos = self._stream.tell()
        self._stream.seek(0, 2)
        end = self._stream.tell()
        self._stream.seek(pos)
        return end - pos

    # ------------------------------------------------------------------ #
    #  PackBits / RLE decompression                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _decode_packbits(data: bytes, expected_size: int) -> bytes:
        """Decode PackBits (Macintosh RLE) compressed data.

        Encoding rules:
          n in [0, 127]   -> copy next (n+1) bytes literally
          n in [-127, -1] -> repeat next byte (1-n) times
          n == -128        -> no-op
        """
        result = bytearray()
        i = 0
        while i < len(data) and len(result) < expected_size:
            n = data[i]
            if n > 127:
                n -= 256  # unsigned -> signed
            i += 1
            if 0 <= n <= 127:
                count = n + 1
                end = min(i + count, len(data))
                result.extend(data[i:end])
                i = end
            elif -127 <= n <= -1:
                count = 1 - n
                if i < len(data):
                    result.extend(bytes([data[i]]) * count)
                    i += 1
            # n == -128: no-op
        return bytes(result[:expected_size])

    def _read_rle_image(self, width: int, height: int) -> bytes:
        """Read an RLE-compressed image (scanline-based, uint16 row lengths)."""
        scanline_sizes = []
        for _ in range(height):
            scanline_sizes.append(self._read_uint16())

        result = bytearray()
        for size in scanline_sizes:
            compressed = self._read(size)
            row = self._decode_packbits(compressed, width)
            result.extend(row)
            if len(row) < width:
                result.extend(b'\x00' * (width - len(row)))

        return bytes(result)

    # ------------------------------------------------------------------ #
    #  v1 / v2 parsing                                                     #
    # ------------------------------------------------------------------ #

    def _parse_v1_v2(self) -> List[BrushTip]:
        count = self._read_uint16()
        brushes = []
        for i in range(count):
            try:
                tip = self._parse_v1_v2_brush(i)
                if tip:
                    brushes.append(tip)
            except (EOFError, struct.error, ValueError):
                break
        return brushes

    def _parse_v1_v2_brush(self, index: int) -> Optional[BrushTip]:
        brush_type = self._read_uint16()
        block_size = self._read_uint32()
        block_end = self._tell() + block_size

        tip = BrushTip(brush_type=brush_type)

        try:
            if brush_type == 1:
                self._parse_computed_brush(tip, index)
            elif brush_type == 2:
                self._parse_sampled_brush_v12(tip, index)
            else:
                self._seek(block_end)
                return None
        except (EOFError, struct.error):
            self._seek(block_end)
            return None

        self._seek(block_end)
        return tip

    def _parse_computed_brush(self, tip: BrushTip, index: int) -> None:
        """Parse a computed (parametric) brush — circle/ellipse with hardness."""
        _misc = self._read_uint32()
        tip.spacing = self._read_uint16()

        if self.version == 2:
            name_len = self._read_uint32()
            if name_len > 0:
                tip.name = self._read_utf16_string(name_len)

        tip.diameter = self._read_uint16()
        tip.roundness = self._read_uint16()
        tip.angle = self._read_uint16()
        tip.hardness = self._read_uint16()

        if not tip.name:
            tip.name = f"Computed Brush {index + 1}"

        size = max(tip.diameter, 1)
        tip.width = size
        tip.height = size
        tip.image_data = self._generate_computed_image(
            size, tip.roundness, tip.angle, tip.hardness
        )

    def _parse_sampled_brush_v12(self, tip: BrushTip, index: int) -> None:
        """Parse a sampled (bitmap) brush from v1/v2 format."""
        _misc = self._read_uint32()
        tip.spacing = self._read_uint16()

        if self.version == 2:
            name_len = self._read_uint32()
            if name_len > 0:
                tip.name = self._read_utf16_string(name_len)

        _anti_alias = self._read_uint8()

        top = self._read_uint16()
        left = self._read_uint16()
        bottom = self._read_uint16()
        right = self._read_uint16()

        tip.width = right - left
        tip.height = bottom - top
        tip.depth = self._read_uint16()
        compression = self._read_uint8()

        if not tip.name:
            tip.name = f"Brush {index + 1}"

        if tip.width <= 0 or tip.height <= 0 or tip.width > 16384 or tip.height > 16384:
            return

        tip.diameter = max(tip.width, tip.height)
        bytes_per_pixel = max(1, tip.depth // 8)
        pixel_width = tip.width * bytes_per_pixel

        if compression == 0:
            tip.image_data = self._read(tip.height * pixel_width)
        elif compression == 1:
            tip.image_data = self._read_rle_image(pixel_width, tip.height)

        if tip.depth == 16:
            tip.image_data = self._convert_16_to_8(tip.image_data)
            tip.depth = 8

        # Clamp to exact size
        expected = tip.width * tip.height
        if len(tip.image_data) < expected:
            tip.image_data += b'\x00' * (expected - len(tip.image_data))
        tip.image_data = tip.image_data[:expected]

    # ------------------------------------------------------------------ #
    #  v6+ parsing                                                         #
    # ------------------------------------------------------------------ #

    def _parse_v6_plus(self) -> List[BrushTip]:
        """Parse ABR version 6+. Tries 8BIM-block approach and direct-sample fallback."""

        # Attempt 1: subversion-based strategy
        if self.subversion >= 2:
            brushes = self._parse_v6_with_8bim()
            if brushes:
                return brushes

        # Attempt 2: direct samples (subversion 1 or fallback)
        self._seek(4)
        brushes = self._parse_v6_samples_direct()
        if brushes:
            return brushes

        # Attempt 3: scan for 8BIM from the beginning
        self._seek(4)
        brushes = self._parse_v6_with_8bim()
        if brushes:
            return brushes

        return []

    def _parse_v6_with_8bim(self) -> List[BrushTip]:
        """Scan for 8BIM resource blocks and parse 'samp' sections."""
        brushes = []

        while self._remaining() >= 12:
            pos = self._tell()
            try:
                tag = self._read(4)
            except EOFError:
                break

            if tag != b'8BIM':
                found = self._scan_for_8bim(pos + 1)
                if not found:
                    break
                continue

            try:
                block_type = self._read(4)
                block_length = self._read_uint32()
            except EOFError:
                break

            block_start = self._tell()

            if block_type == b'samp':
                samp_brushes = self._parse_samp_block(block_length)
                brushes.extend(samp_brushes)

            self._seek(block_start + block_length)

        return brushes

    def _scan_for_8bim(self, start: int) -> bool:
        """Scan forward (up to 64 KiB) looking for a '8BIM' tag."""
        self._seek(start)
        max_scan = min(65536, self._remaining())
        data = self._stream.read(max_scan)
        idx = data.find(b'8BIM')
        if idx >= 0:
            self._seek(start + idx)
            return True
        return False

    def _parse_v6_samples_direct(self) -> List[BrushTip]:
        """Parse v6 assuming brush records follow directly (no 8BIM wrapper)."""
        brushes = []
        idx = 0
        while self._remaining() >= 4:
            try:
                brush_length = self._read_uint32()
            except EOFError:
                break
            if brush_length <= 0 or brush_length > self._remaining():
                break

            brush_end = self._tell() + brush_length
            try:
                tip = self._parse_v6_brush(brush_length, idx)
                if tip:
                    brushes.append(tip)
            except (EOFError, struct.error, ValueError):
                pass

            idx += 1
            self._seek(brush_end)

        return brushes

    def _parse_samp_block(self, block_length: int) -> List[BrushTip]:
        """Parse the contents of a 'samp' 8BIM block."""
        block_end = self._tell() + block_length
        brushes = []
        idx = 0

        while self._tell() < block_end - 4:
            try:
                brush_length = self._read_uint32()
            except EOFError:
                break

            if brush_length <= 0 or brush_length > (block_end - self._tell()):
                break

            brush_end = self._tell() + brush_length
            try:
                tip = self._parse_v6_brush(brush_length, idx)
                if tip:
                    brushes.append(tip)
            except (EOFError, struct.error, ValueError):
                pass

            idx += 1
            self._seek(brush_end)

        return brushes

    def _parse_v6_brush(self, brush_length: int, index: int) -> Optional[BrushTip]:
        """Parse a single v6+ brush. Tries multiple layout strategies."""
        brush_start = self._tell()
        brush_data = self._data[brush_start:brush_start + brush_length]

        # Strategy 1: Simple layout (subversion 1 style)
        #   [4 unknown] [bounds 4×uint16] [depth uint16] [compress uint8] [data]
        tip = self._try_parse_v6_simple(brush_data, index)
        if tip:
            return tip

        # Strategy 2: Named layout (subversion 2 style)
        #   [4 unknown] [4 name_len] [UTF-16 name] [1 unknown] ... [bounds] [depth] [compress] [data]
        tip = self._try_parse_v6_named(brush_data, index)
        if tip:
            return tip

        # Strategy 3: Brute-force scan for a valid bounds pattern
        tip = self._try_parse_v6_scan(brush_data, index)
        if tip:
            return tip

        return None

    # ---------- v6 layout strategies ----------

    def _try_parse_v6_simple(self, data: bytes, index: int) -> Optional[BrushTip]:
        """Simple v6 layout: 4 unk + bounds(4×u16) + depth(u16) + compress(u8) + pixels."""
        if len(data) < 15:
            return None

        offset = 4
        top, left, bottom, right = struct.unpack_from('>HHHH', data, offset)
        width = right - left
        height = bottom - top

        if not (0 < width <= 16384 and 0 < height <= 16384):
            return None

        offset += 8
        depth = struct.unpack_from('>H', data, offset)[0]
        offset += 2
        if depth not in (8, 16):
            return None

        compression = data[offset]
        offset += 1
        if compression not in (0, 1):
            return None

        image_data = self._extract_image(data[offset:], width, height, depth, compression)
        if image_data is None:
            return None

        tip = BrushTip(
            name=f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            diameter=max(width, height), brush_type=2,
            image_data=image_data,
        )
        if depth == 16:
            tip.image_data = self._convert_16_to_8(tip.image_data)
            tip.depth = 8
        return tip

    def _try_parse_v6_named(self, data: bytes, index: int) -> Optional[BrushTip]:
        """Named v6 layout with UTF-16 brush name."""
        if len(data) < 20:
            return None

        offset = 4  # skip unknown
        name_len = struct.unpack_from('>I', data, offset)[0]
        offset += 4

        if name_len > 10000 or offset + name_len * 2 >= len(data):
            return None

        name = ""
        if name_len > 0:
            name_bytes = data[offset:offset + name_len * 2]
            name = name_bytes.decode('utf-16-be', errors='replace').rstrip('\x00')
            offset += name_len * 2

        if offset >= len(data):
            return None

        # Skip 1 unknown byte
        offset += 1

        # Try to extract spacing (2 bytes right after the unknown byte)
        spacing = 25
        if offset + 2 <= len(data):
            raw_spacing = struct.unpack_from('>H', data, offset)[0]
            if 1 <= raw_spacing <= 1000:
                spacing = raw_spacing

        # Scan for valid bounds from current position
        result = self._find_bounds_in_data(data, offset)
        if result is None:
            return None

        bounds_offset, top, left, bottom, right, depth, compression, bounds_type = result
        width = right - left
        height = bottom - top

        if bounds_type == 'short':
            img_offset = bounds_offset + 8 + 2 + 1   # 4×u16 + depth(u16) + compress(u8)
        else:
            img_offset = bounds_offset + 16 + 2 + 1  # 4×u32 + depth(u16) + compress(u8)

        image_data = self._extract_image(data[img_offset:], width, height, depth, compression)
        if image_data is None:
            return None

        tip = BrushTip(
            name=name if name else f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            diameter=max(width, height), brush_type=2,
            spacing=spacing, image_data=image_data,
        )
        if depth == 16:
            tip.image_data = self._convert_16_to_8(tip.image_data)
            tip.depth = 8
        return tip

    def _try_parse_v6_scan(self, data: bytes, index: int) -> Optional[BrushTip]:
        """Last resort: scan the entire brush record for a valid bounds pattern."""
        result = self._find_bounds_in_data(data, 4)
        if result is None:
            return None

        bounds_offset, top, left, bottom, right, depth, compression, bounds_type = result
        width = right - left
        height = bottom - top

        if bounds_type == 'short':
            img_offset = bounds_offset + 8 + 2 + 1
        else:
            img_offset = bounds_offset + 16 + 2 + 1

        image_data = self._extract_image(data[img_offset:], width, height, depth, compression)
        if image_data is None:
            return None

        tip = BrushTip(
            name=f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            diameter=max(width, height), brush_type=2,
            image_data=image_data,
        )
        if depth == 16:
            tip.image_data = self._convert_16_to_8(tip.image_data)
            tip.depth = 8
        return tip

    # ---------- Bounds / image extraction helpers ----------

    def _find_bounds_in_data(self, data: bytes, start: int) -> Optional[tuple]:
        """Scan *data* for a valid (top, left, bottom, right, depth, compression) pattern.

        Returns (offset, top, left, bottom, right, depth, compression, 'short'|'long')
        or None.
        """
        end_u16 = min(start + 120, len(data) - 11)
        for offset in range(start, end_u16):
            top, left, bottom, right = struct.unpack_from('>HHHH', data, offset)
            w, h = right - left, bottom - top
            if 1 <= w <= 16384 and 1 <= h <= 16384 and top <= 16384 and left <= 16384:
                depth = struct.unpack_from('>H', data, offset + 8)[0]
                if depth in (8, 16):
                    comp = data[offset + 10]
                    if comp in (0, 1):
                        remaining = len(data) - (offset + 11)
                        img_size = w * h * max(1, depth // 8)
                        if remaining >= min(img_size, img_size // 4):
                            return (offset, top, left, bottom, right, depth, comp, 'short')

        end_u32 = min(start + 120, len(data) - 19)
        for offset in range(start, end_u32):
            top, left, bottom, right = struct.unpack_from('>IIII', data, offset)
            w, h = right - left, bottom - top
            if 1 <= w <= 16384 and 1 <= h <= 16384 and top <= 16384 and left <= 16384:
                depth = struct.unpack_from('>H', data, offset + 16)[0]
                if depth in (8, 16):
                    comp = data[offset + 18]
                    if comp in (0, 1):
                        remaining = len(data) - (offset + 19)
                        img_size = w * h * max(1, depth // 8)
                        if remaining >= min(img_size, img_size // 4):
                            return (offset, top, left, bottom, right, depth, comp, 'long')

        return None

    def _extract_image(self, data: bytes, width: int, height: int,
                       depth: int, compression: int) -> Optional[bytes]:
        """Extract raw pixel data from a (possibly RLE-compressed) byte buffer."""
        bpp = max(1, depth // 8)
        expected = width * height * bpp

        if compression == 0:
            if len(data) < expected:
                return None
            return data[:expected]

        elif compression == 1:
            f = io.BytesIO(data)
            try:
                scanline_sizes = [struct.unpack('>H', f.read(2))[0] for _ in range(height)]
            except struct.error:
                return None

            result = bytearray()
            row_width = width * bpp
            for size in scanline_sizes:
                compressed = f.read(size)
                if len(compressed) < size:
                    compressed += b'\x00' * (size - len(compressed))
                row = self._decode_packbits(compressed, row_width)
                result.extend(row)
                if len(row) < row_width:
                    result.extend(b'\x00' * (row_width - len(row)))

            return bytes(result[:expected])

        return None

    # ------------------------------------------------------------------ #
    #  Conversion helpers                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _convert_16_to_8(data: bytes) -> bytes:
        """Down-convert 16-bit big-endian grayscale to 8-bit."""
        result = bytearray(len(data) // 2)
        for i in range(0, len(data) - 1, 2):
            result[i // 2] = data[i]  # take the high byte
        return bytes(result)

    @staticmethod
    def _generate_computed_image(size: int, roundness: int, angle: int, hardness: int) -> bytes:
        """Render a grayscale brush image for a computed (parametric) brush."""
        if size <= 0:
            size = 10

        center = size / 2.0
        radius = size / 2.0
        pixels = bytearray(size * size)

        angle_rad = math.radians(angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        r_factor = max(roundness / 100.0, 0.01)
        h_factor = hardness / 100.0

        for y in range(size):
            for x in range(size):
                dx = x - center + 0.5
                dy = y - center + 0.5

                rx = dx * cos_a + dy * sin_a
                ry = (-dx * sin_a + dy * cos_a) / r_factor

                dist = math.sqrt(rx * rx + ry * ry) / radius

                if dist >= 1.0:
                    val = 0
                elif h_factor >= 1.0:
                    val = 255
                elif dist <= h_factor:
                    val = 255
                else:
                    t = (dist - h_factor) / (1.0 - h_factor)
                    val = int(255 * (1.0 - t * t))

                pixels[y * size + x] = max(0, min(255, val))

        return bytes(pixels)


# ------------------------------------------------------------------ #
#  Convenience wrapper                                                 #
# ------------------------------------------------------------------ #

def parse_abr(filepath: str) -> List[BrushTip]:
    """Parse an ABR file and return a list of BrushTip objects."""
    parser = ABRParser(filepath=filepath)
    return parser.parse()
