"""
ABR (Adobe Brush) file format parser — v2.

Supports ABR versions 1, 2, and 6+ (including v6, v7, v9, v10).

New in v2:
  - Photoshop descriptor ('desc') parsing for brush dynamics (spacing, opacity,
    flow, scatter, size jitter, angle, roundness, pressure curves, dual brush).
  - RGBA brush tips (colour type 2 = RGB, type 6 = RGBA) in addition to grayscale.
  - Pattern/texture extraction from 'patt' 8BIM blocks.
  - Hardened error recovery: every block parse is wrapped with boundary checks,
    bad-data guards, and graceful fallback strategies.
"""

import struct
import io
import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

log = logging.getLogger("abr_parser")


# ===================================================================== #
#  Data classes                                                          #
# ===================================================================== #

@dataclass
class BrushDynamics:
    """Photoshop brush engine dynamics extracted from a descriptor block."""
    spacing: int = 25
    opacity: int = 100
    flow: int = 100
    size_jitter: int = 0
    angle_jitter: int = 0
    roundness_jitter: int = 0
    scatter: int = 0
    count: int = 1
    hardness: int = 100
    angle: int = 0
    roundness: int = 100
    flip_x: bool = False
    flip_y: bool = False
    size_pressure_curve: List[Tuple[float, float]] = field(default_factory=list)
    opacity_pressure_curve: List[Tuple[float, float]] = field(default_factory=list)
    flow_pressure_curve: List[Tuple[float, float]] = field(default_factory=list)
    dual_brush_enabled: bool = False
    dual_brush_tip_index: int = -1
    dual_brush_diameter: int = 0
    dual_brush_spacing: int = 25
    dual_brush_scatter: int = 0
    dual_brush_count: int = 1
    dual_brush_mode: str = "multiply"  # PS blend mode
    dual_brush_flip: bool = False
    dual_brush_roundness: int = 100
    dual_brush_angle: int = 0
    dual_brush_hardness: int = 100
    wet_edges: bool = False
    noise: bool = False
    smoothing: bool = False
    # Color dynamics
    hue_jitter: int = 0           # 0-100 %
    saturation_jitter: int = 0    # 0-100 %
    brightness_jitter: int = 0    # 0-100 %
    purity: int = 0               # foreground/background mixing, -100..100
    # Texture / pattern overlay
    texture_enabled: bool = False
    texture_pattern_name: str = ""
    texture_scale: int = 100      # 1-1000 %
    texture_depth: int = 100      # 0-100 %
    texture_mode: str = ""        # blend mode string
    # Airbrush
    airbrush: bool = False
    # Scatter axis
    scatter_both_axes: bool = False


@dataclass
class BrushPattern:
    """A pattern/texture extracted from a 'patt' block."""
    name: str = ""
    pattern_id: str = ""
    width: int = 0
    height: int = 0
    channels: int = 1
    image_data: bytes = b""


@dataclass
class BrushTip:
    """A single brush tip extracted from an ABR file."""
    name: str = ""
    width: int = 0
    height: int = 0
    depth: int = 8
    channels: int = 1       # 1=grayscale, 3=RGB, 4=RGBA
    image_data: bytes = b""
    spacing: int = 25
    diameter: int = 0
    angle: int = 0
    roundness: int = 100
    hardness: int = 100
    brush_type: int = 2     # 1=computed, 2=sampled
    dynamics: Optional[BrushDynamics] = None


class ABRParser:
    """Parser for Adobe Brush (.abr) files."""

    def __init__(self, filepath: str = None, data: bytes = None):
        if filepath:
            with open(filepath, 'rb') as f:
                self._data = f.read()
        elif data is not None:
            self._data = data
        else:
            raise ValueError("Either filepath or data must be provided")

        self._stream = io.BytesIO(self._data)
        self.version = 0
        self.subversion = 0
        self.patterns: List[BrushPattern] = []
        self._descriptors: List[BrushDynamics] = []

    def parse(self) -> List[BrushTip]:
        """Parse the ABR data and return a list of BrushTip objects."""
        self._stream.seek(0)
        self.patterns = []
        self._descriptors = []

        try:
            self.version = self._read_uint16()
        except (EOFError, struct.error):
            log.warning("File too short to contain ABR header")
            return []

        if self.version in (1, 2):
            return self._parse_v1_v2()
        elif self.version >= 6:
            try:
                self.subversion = self._read_uint16()
            except (EOFError, struct.error):
                log.warning("File too short for v6+ subversion")
                return []
            return self._parse_v6_plus()
        else:
            log.warning("Unsupported ABR version: %d", self.version)
            return []

    # ================================================================= #
    #  Binary reading helpers                                             #
    # ================================================================= #

    def _read(self, n: int) -> bytes:
        data = self._stream.read(n)
        if len(data) < n:
            raise EOFError(f"Expected {n} bytes, got {len(data)}")
        return data

    def _try_read(self, n: int) -> Optional[bytes]:
        data = self._stream.read(n)
        return data if len(data) == n else None

    def _read_uint8(self) -> int:
        return struct.unpack('>B', self._read(1))[0]

    def _read_uint16(self) -> int:
        return struct.unpack('>H', self._read(2))[0]

    def _read_int16(self) -> int:
        return struct.unpack('>h', self._read(2))[0]

    def _read_uint32(self) -> int:
        return struct.unpack('>I', self._read(4))[0]

    def _read_int32(self) -> int:
        return struct.unpack('>i', self._read(4))[0]

    def _read_float64(self) -> float:
        return struct.unpack('>d', self._read(8))[0]

    def _read_utf16_string(self, char_count: int) -> str:
        if char_count <= 0:
            return ""
        raw = self._read(char_count * 2)
        return raw.decode('utf-16-be', errors='replace').rstrip('\x00')

    def _read_pascal_string(self) -> str:
        length = self._read_uint8()
        if length == 0:
            return ""
        raw = self._read(length)
        return raw.decode('latin-1', errors='replace')

    def _read_unicode_string(self) -> str:
        char_count = self._read_uint32()
        if char_count == 0:
            return ""
        if char_count > 100000:
            raise ValueError(f"Unreasonable unicode string length: {char_count}")
        return self._read_utf16_string(char_count)

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

    # ================================================================= #
    #  PackBits / RLE decompression                                       #
    # ================================================================= #

    @staticmethod
    def _decode_packbits(data: bytes, expected_size: int) -> bytes:
        result = bytearray()
        i = 0
        size = len(data)
        while i < size and len(result) < expected_size:
            n = data[i]
            if n > 127:
                n -= 256
            i += 1
            if 0 <= n <= 127:
                count = n + 1
                end = min(i + count, size)
                result.extend(data[i:end])
                i = end
            elif -127 <= n <= -1:
                count = 1 - n
                if i < size:
                    result.extend(bytes([data[i]]) * count)
                    i += 1
        return bytes(result[:expected_size])

    def _read_rle_image(self, row_bytes: int, height: int) -> bytes:
        scanline_sizes = []
        for _ in range(height):
            scanline_sizes.append(self._read_uint16())

        result = bytearray()
        for sl_size in scanline_sizes:
            compressed = self._read(sl_size)
            row = self._decode_packbits(compressed, row_bytes)
            result.extend(row)
            if len(row) < row_bytes:
                result.extend(b'\x00' * (row_bytes - len(row)))

        return bytes(result)

    # ================================================================= #
    #  Photoshop Descriptor parser (for 'desc' blocks)                    #
    # ================================================================= #

    def _read_descriptor_key(self) -> str:
        length = self._read_uint32()
        if length == 0:
            length = 4
        if length > 1000:
            raise ValueError(f"Unreasonable key length: {length}")
        return self._read(length).decode('ascii', errors='replace')

    def _parse_descriptor(self) -> Dict[str, Any]:
        """Parse a Photoshop Descriptor structure (recursive key-value store)."""
        _class_name = self._read_unicode_string()
        _class_id = self._read_descriptor_key()

        count = self._read_uint32()
        if count > 10000:
            raise ValueError(f"Unreasonable descriptor item count: {count}")

        result: Dict[str, Any] = {}

        for _ in range(count):
            try:
                key = self._read_descriptor_key()
                value = self._parse_descriptor_item()
                result[key] = value
            except (EOFError, struct.error, UnicodeDecodeError, ValueError):
                break

        return result

    def _parse_descriptor_item(self) -> Any:
        os_type = self._read(4).decode('ascii', errors='replace')

        if os_type == 'bool':
            return self._read_uint8() != 0
        elif os_type == 'long':
            return self._read_int32()
        elif os_type == 'doub':
            return self._read_float64()
        elif os_type == 'UntF':
            _units = self._read(4).decode('ascii', errors='replace')
            value = self._read_float64()
            return {'units': _units, 'value': value}
        elif os_type == 'enum':
            _type_id = self._read_descriptor_key()
            val_id = self._read_descriptor_key()
            return {'type': _type_id, 'value': val_id}
        elif os_type == 'TEXT':
            return self._read_unicode_string()
        elif os_type == 'tdta':
            length = self._read_uint32()
            if length > 10_000_000:
                raise ValueError(f"Unreasonable tdta length: {length}")
            return self._read(length)
        elif os_type in ('Objc', 'GlbO', 'GlbC'):
            return self._parse_descriptor()
        elif os_type == 'VlLs':
            count = self._read_uint32()
            if count > 100000:
                raise ValueError(f"Unreasonable list length: {count}")
            items = []
            for _ in range(count):
                try:
                    items.append(self._parse_descriptor_item())
                except (EOFError, struct.error):
                    break
            return items
        elif os_type == 'obj ':
            return self._parse_descriptor()
        elif os_type == 'type' or os_type == 'GlbC':
            return self._read_descriptor_key()
        else:
            log.debug("Unknown descriptor type: %s", os_type)
            return None

    def _descriptor_to_dynamics(self, desc: Dict[str, Any]) -> BrushDynamics:
        """Map a Photoshop brush descriptor dict to BrushDynamics."""
        dyn = BrushDynamics()

        val = self._desc_get_num(desc, 'Spcn')
        if val is not None:
            dyn.spacing = max(1, min(1000, int(val)))

        val = self._desc_get_num(desc, 'Hrdn')
        if val is not None:
            dyn.hardness = max(0, min(100, int(val)))

        val = self._desc_get_num(desc, 'Angl')
        if val is not None:
            dyn.angle = int(val) % 360

        val = self._desc_get_num(desc, 'Rndn')
        if val is not None:
            dyn.roundness = max(0, min(100, int(val)))

        dyn.flip_x = bool(desc.get('flipX', False))
        dyn.flip_y = bool(desc.get('flipY', False))

        # Transfer (opacity / flow)
        transfer = desc.get('Trns', {})
        if isinstance(transfer, dict):
            val = self._desc_get_num(transfer, 'Opct')
            if val is not None:
                dyn.opacity = max(0, min(100, int(val)))
            val = self._desc_get_num(transfer, 'Flw ')
            if val is not None:
                dyn.flow = max(0, min(100, int(val)))
            dyn.opacity_pressure_curve = self._extract_curve(transfer, 'opVr')
            dyn.flow_pressure_curve = self._extract_curve(transfer, 'flVr')

        # Shape dynamics
        shape_dyn = desc.get('ShpD', {})
        if isinstance(shape_dyn, dict):
            val = self._desc_get_num(shape_dyn, 'SzJt')
            if val is not None:
                dyn.size_jitter = max(0, min(100, int(val)))
            val = self._desc_get_num(shape_dyn, 'AnJt')
            if val is not None:
                dyn.angle_jitter = max(0, min(360, int(val)))
            val = self._desc_get_num(shape_dyn, 'RnJt')
            if val is not None:
                dyn.roundness_jitter = max(0, min(100, int(val)))
            dyn.size_pressure_curve = self._extract_curve(shape_dyn, 'szVr')

        # Scattering
        scatter_desc = desc.get('Sctr', {})
        if isinstance(scatter_desc, dict):
            val = self._desc_get_num(scatter_desc, 'Sctr')
            if val is not None:
                dyn.scatter = max(0, min(1000, int(val)))
            cnt = scatter_desc.get('Cnt ', 1)
            if isinstance(cnt, int):
                dyn.count = max(1, min(16, cnt))
            # Both axes flag
            both = scatter_desc.get('BthA', False)
            dyn.scatter_both_axes = bool(both)

        # Dual brush
        dual = desc.get('DlBr', {})
        if isinstance(dual, dict) and dual:
            dyn.dual_brush_enabled = True
            val = self._desc_get_num(dual, 'Dmtr')
            if val is not None:
                dyn.dual_brush_diameter = max(1, int(val))
            val = self._desc_get_num(dual, 'Spcn')
            if val is not None:
                dyn.dual_brush_spacing = max(1, min(1000, int(val)))
            val = self._desc_get_num(dual, 'Sctr')
            if val is not None:
                dyn.dual_brush_scatter = max(0, int(val))
            val = self._desc_get_num(dual, 'Cnt ')
            if val is not None:
                dyn.dual_brush_count = max(1, int(val))
            mode = dual.get('Md  ', {})
            if isinstance(mode, dict):
                dyn.dual_brush_mode = str(mode.get('value', 'multiply'))
            dyn.dual_brush_flip = bool(dual.get('flipX', False))
            val = self._desc_get_num(dual, 'Rndn')
            if val is not None:
                dyn.dual_brush_roundness = max(0, min(100, int(val)))
            val = self._desc_get_num(dual, 'Angl')
            if val is not None:
                dyn.dual_brush_angle = int(val)
            val = self._desc_get_num(dual, 'Hrdn')
            if val is not None:
                dyn.dual_brush_hardness = max(0, min(100, int(val)))

        # Color dynamics
        color_dyn = desc.get('ClrD', {})
        if isinstance(color_dyn, dict):
            val = self._desc_get_num(color_dyn, 'H   ')
            if val is not None:
                dyn.hue_jitter = max(0, min(100, int(val)))
            val = self._desc_get_num(color_dyn, 'Strt')
            if val is not None:
                dyn.saturation_jitter = max(0, min(100, int(val)))
            val = self._desc_get_num(color_dyn, 'Brgh')
            if val is not None:
                dyn.brightness_jitter = max(0, min(100, int(val)))
            val = self._desc_get_num(color_dyn, 'Prty')
            if val is not None:
                dyn.purity = max(-100, min(100, int(val)))

        # Texture / pattern overlay
        texture = desc.get('Txtr', {})
        if isinstance(texture, dict) and texture:
            dyn.texture_enabled = True
            patt = texture.get('Ptrn', {})
            if isinstance(patt, dict):
                dyn.texture_pattern_name = str(patt.get('Nm  ', ''))
            val = self._desc_get_num(texture, 'Scl ')
            if val is not None:
                dyn.texture_scale = max(1, min(1000, int(val)))
            val = self._desc_get_num(texture, 'textureDepth')
            if val is not None:
                dyn.texture_depth = max(0, min(100, int(val)))
            mode = texture.get('Md  ', {})
            if isinstance(mode, dict):
                dyn.texture_mode = str(mode.get('value', ''))

        # Airbrush
        dyn.airbrush = bool(desc.get('usAB', False))

        # Toggles
        dyn.wet_edges = bool(desc.get('Wtdg', False))
        dyn.noise = bool(desc.get('Nose', False))
        dyn.smoothing = bool(desc.get('Smth', False))

        return dyn

    @staticmethod
    def _desc_get_num(desc: Dict[str, Any], key: str) -> Optional[float]:
        val = desc.get(key)
        if val is None:
            return None
        if isinstance(val, dict) and 'value' in val:
            return float(val['value'])
        if isinstance(val, (int, float)):
            return float(val)
        return None

    @staticmethod
    def _extract_curve(desc: Dict[str, Any], key: str) -> List[Tuple[float, float]]:
        var = desc.get(key)
        if not isinstance(var, dict):
            return []

        curve_data = var.get('Crv ', [])
        if not isinstance(curve_data, list):
            return []

        points = []
        for pt in curve_data:
            if isinstance(pt, dict):
                inp = pt.get('Hrzn', pt.get('input', 0))
                out = pt.get('Vrtc', pt.get('output', 0))
                if isinstance(inp, dict):
                    inp = inp.get('value', 0)
                if isinstance(out, dict):
                    out = out.get('value', 0)
                inp_f = float(inp) / 255.0 if float(inp) > 1.0 else float(inp)
                out_f = float(out) / 255.0 if float(out) > 1.0 else float(out)
                points.append((
                    max(0.0, min(1.0, inp_f)),
                    max(0.0, min(1.0, out_f)),
                ))
        return points

    # ================================================================= #
    #  Pattern ('patt') block parser                                      #
    # ================================================================= #

    def _parse_patt_block(self, block_length: int) -> None:
        block_end = self._tell() + block_length

        while self._tell() < block_end - 8:
            pat_start = self._tell()
            try:
                pat = self._parse_single_pattern(block_end)
                if pat and pat.width > 0 and pat.height > 0:
                    self.patterns.append(pat)
            except (EOFError, struct.error, ValueError) as exc:
                log.debug("Pattern parse error at offset %d: %s", pat_start, exc)
                break

            # Pad to 4-byte boundary
            pos = self._tell()
            pad = (4 - (pos % 4)) % 4
            if pad and self._remaining() >= pad:
                self._read(pad)

    def _parse_single_pattern(self, block_end: int) -> Optional[BrushPattern]:
        if self._tell() >= block_end - 4:
            return None

        version = self._read_uint32()
        if version != 1:
            return None

        image_mode = self._read_uint32()
        height = self._read_uint16()
        width = self._read_uint16()

        if width <= 0 or height <= 0 or width > 16384 or height > 16384:
            return None

        name = self._read_unicode_string()
        unique_id = self._read_pascal_string()
        # Pad pascal string to even
        if (len(unique_id) + 1) % 2 != 0:
            self._read(1)

        if image_mode == 1:
            num_channels = 1
        elif image_mode == 3:
            num_channels = 3
        elif image_mode == 9:
            num_channels = 3
        elif image_mode == 2:
            num_channels = 1
            # Indexed colour mode: skip colour table
            self._read(256 * 3)
            self._read(4)  # transparency count
        else:
            return None

        # VirtualMemoryArrayList
        _vma_version = self._read_uint32()
        _vma_length = self._read_uint32()
        vma_end = self._tell() + _vma_length

        if vma_end > block_end:
            vma_end = block_end

        _top = self._read_uint32()
        _left = self._read_uint32()
        _bottom = self._read_uint32()
        _right = self._read_uint32()
        _max_channels = self._read_uint32()

        pixel_data_per_channel: Dict[int, bytes] = {}
        for ch_idx in range(_max_channels + 2):
            if self._tell() >= vma_end:
                break
            try:
                is_written = self._read_uint32()
            except EOFError:
                break
            if is_written == 0:
                continue
            try:
                ch_length = self._read_uint32()
            except EOFError:
                break
            ch_end = self._tell() + ch_length
            if ch_length <= 0 or ch_end > vma_end:
                self._seek(min(ch_end, vma_end))
                continue

            try:
                _ch_depth = self._read_uint32()
                ch_top = self._read_uint32()
                ch_left = self._read_uint32()
                ch_bottom = self._read_uint32()
                ch_right = self._read_uint32()
                _ch_pixel_depth = self._read_uint16()
                ch_compression = self._read_uint8()

                ch_w = ch_right - ch_left
                ch_h = ch_bottom - ch_top

                if 0 < ch_w <= 16384 and 0 < ch_h <= 16384:
                    if ch_compression == 0:
                        ch_data = self._read(ch_w * ch_h)
                    elif ch_compression == 1:
                        ch_data = self._read_rle_image(ch_w, ch_h)
                    else:
                        ch_data = b''

                    if len(ch_data) >= ch_w * ch_h:
                        pixel_data_per_channel[ch_idx] = ch_data
            except (EOFError, struct.error):
                pass

            self._seek(ch_end)

        self._seek(vma_end)

        # Interleave channels
        if len(pixel_data_per_channel) >= num_channels:
            pixel_count = width * height
            interleaved = bytearray(pixel_count * num_channels)
            for ch in range(num_channels):
                ch_data = pixel_data_per_channel.get(ch, b'\x00' * pixel_count)
                for px in range(min(pixel_count, len(ch_data))):
                    interleaved[px * num_channels + ch] = ch_data[px]

            return BrushPattern(
                name=name, pattern_id=unique_id,
                width=width, height=height,
                channels=num_channels,
                image_data=bytes(interleaved),
            )

        return None

    # ================================================================= #
    #  v1 / v2 parsing                                                    #
    # ================================================================= #

    def _parse_v1_v2(self) -> List[BrushTip]:
        try:
            count = self._read_uint16()
        except (EOFError, struct.error):
            return []

        if count > 10000:
            log.warning("Unreasonable brush count %d, capping at 10000", count)
            count = 10000

        brushes = []
        for i in range(count):
            try:
                tip = self._parse_v1_v2_brush(i)
                if tip:
                    brushes.append(tip)
            except (EOFError, struct.error, ValueError, OverflowError) as exc:
                log.debug("v1/v2 brush %d parse error: %s", i, exc)
                if self._remaining() < 6:
                    break
                continue
        return brushes

    def _parse_v1_v2_brush(self, index: int) -> Optional[BrushTip]:
        brush_type = self._read_uint16()
        block_size = self._read_uint32()

        if block_size > len(self._data):
            return None

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
        except (EOFError, struct.error, OverflowError):
            self._seek(block_end)
            return None

        self._seek(block_end)
        return tip

    def _parse_computed_brush(self, tip: BrushTip, index: int) -> None:
        _misc = self._read_uint32()
        tip.spacing = self._read_uint16()

        if self.version == 2:
            name_len = self._read_uint32()
            if 0 < name_len < 10000:
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
        tip.channels = 1
        tip.image_data = self._generate_computed_image(
            size, tip.roundness, tip.angle, tip.hardness
        )

    def _parse_sampled_brush_v12(self, tip: BrushTip, index: int) -> None:
        _misc = self._read_uint32()
        tip.spacing = self._read_uint16()

        if self.version == 2:
            name_len = self._read_uint32()
            if 0 < name_len < 10000:
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

        tip.channels = 1
        expected = tip.width * tip.height
        if len(tip.image_data) < expected:
            tip.image_data += b'\x00' * (expected - len(tip.image_data))
        tip.image_data = tip.image_data[:expected]

    # ================================================================= #
    #  v6+ parsing                                                        #
    # ================================================================= #

    def _parse_v6_plus(self) -> List[BrushTip]:
        # First pass: collect desc, patt, samp blocks
        brushes = self._parse_v6_full_8bim()
        if brushes:
            self._assign_dynamics(brushes)
            return brushes

        # Fallback: direct samples
        self._seek(4)
        brushes = self._parse_v6_samples_direct()
        if brushes:
            return brushes

        # Last resort: re-scan
        self._seek(4)
        brushes = self._parse_v6_full_8bim()
        return brushes

    def _parse_v6_full_8bim(self) -> List[BrushTip]:
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

            if block_length > len(self._data):
                log.debug("8BIM block length %d exceeds file size", block_length)
                found = self._scan_for_8bim(self._tell())
                if not found:
                    break
                continue

            block_start = self._tell()
            block_end = block_start + block_length

            try:
                if block_type == b'desc':
                    desc = self._parse_descriptor()
                    dyn = self._descriptor_to_dynamics(desc)
                    self._descriptors.append(dyn)
                elif block_type == b'patt':
                    self._parse_patt_block(block_length)
                elif block_type == b'samp':
                    samp_brushes = self._parse_samp_block(block_length)
                    brushes.extend(samp_brushes)
            except (EOFError, struct.error, ValueError, UnicodeDecodeError) as exc:
                log.debug("Error in 8BIM %s at %d: %s",
                          block_type.decode('ascii', errors='replace'), pos, exc)

            self._seek(block_end)

        return brushes

    def _assign_dynamics(self, brushes: List[BrushTip]) -> None:
        for i, tip in enumerate(brushes):
            if i < len(self._descriptors):
                dyn = self._descriptors[i]
                tip.dynamics = dyn
                if dyn.spacing > 0:
                    tip.spacing = dyn.spacing

    def _scan_for_8bim(self, start: int) -> bool:
        self._seek(start)
        max_scan = min(65536, self._remaining())
        if max_scan < 4:
            return False
        data = self._stream.read(max_scan)
        idx = data.find(b'8BIM')
        if idx >= 0:
            self._seek(start + idx)
            return True
        return False

    def _parse_v6_samples_direct(self) -> List[BrushTip]:
        brushes = []
        idx = 0
        consecutive_failures = 0
        while self._remaining() >= 4 and consecutive_failures < 10:
            try:
                brush_length = self._read_uint32()
            except EOFError:
                break

            if brush_length <= 0 or brush_length > self._remaining():
                consecutive_failures += 1
                continue

            brush_end = self._tell() + brush_length
            try:
                tip = self._parse_v6_brush(brush_length, idx)
                if tip:
                    brushes.append(tip)
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except (EOFError, struct.error, ValueError):
                consecutive_failures += 1

            idx += 1
            self._seek(brush_end)

        return brushes

    def _parse_samp_block(self, block_length: int) -> List[BrushTip]:
        block_end = self._tell() + block_length
        brushes = []
        idx = 0
        consecutive_failures = 0

        while self._tell() < block_end - 4 and consecutive_failures < 10:
            try:
                brush_length = self._read_uint32()
            except EOFError:
                break

            if brush_length <= 0 or brush_length > (block_end - self._tell()):
                consecutive_failures += 1
                break

            brush_end = self._tell() + brush_length
            try:
                tip = self._parse_v6_brush(brush_length, idx)
                if tip:
                    brushes.append(tip)
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except (EOFError, struct.error, ValueError) as exc:
                log.debug("samp brush %d error: %s", idx, exc)
                consecutive_failures += 1

            idx += 1
            self._seek(brush_end)
            # Align to 4-byte boundary between brush entries
            pos = self._tell()
            pad = (4 - (pos % 4)) % 4
            if pad and pos + pad < block_end:
                self._seek(pos + pad)

        return brushes

    def _parse_v6_brush(self, brush_length: int, index: int) -> Optional[BrushTip]:
        brush_start = self._tell()
        end = min(brush_start + brush_length, len(self._data))
        brush_data = self._data[brush_start:end]

        if len(brush_data) < 15:
            return None

        # Strategy 0: VMA layout with null-terminated ASCII ID
        tip = self._try_parse_v6_vma(brush_data, index)
        if tip:
            return tip

        # Strategy 1: Named layout (most common in v6+)
        tip = self._try_parse_v6_named(brush_data, index)
        if tip:
            return tip

        # Strategy 2: Simple layout
        tip = self._try_parse_v6_simple(brush_data, index)
        if tip:
            return tip

        # Strategy 3: Brute-force scan
        tip = self._try_parse_v6_scan(brush_data, index)
        if tip:
            return tip

        return None

    # ---------- v6 layout strategies ----------

    def _try_parse_v6_vma(self, data: bytes, index: int) -> Optional[BrushTip]:
        """Strategy for VMA-format brushes with null-terminated ASCII IDs."""
        if len(data) < 80:
            return None

        # Find null-terminated ASCII ID at start of brush data
        null_pos = -1
        for i in range(min(256, len(data))):
            if data[i] == 0:
                null_pos = i
                break
        if null_pos < 4:
            return None

        # Verify the ID is printable ASCII
        id_bytes = data[:null_pos]
        if not all(0x20 <= b < 0x7f for b in id_bytes):
            return None
        brush_name = id_bytes.decode('ascii', errors='replace')

        # After null: type(1) + uint32(4) + uint16(2) + data_len(4) = 11 bytes
        pos = null_pos + 1
        if pos + 11 > len(data):
            return None
        pos += 1   # type byte
        pos += 4   # misc uint32
        pos += 2   # unknown uint16
        vma_data_len = struct.unpack_from('>I', data, pos)[0]
        pos += 4

        if vma_data_len <= 20:
            return None
        vma_end = pos + vma_data_len
        if vma_end > len(data):
            vma_end = len(data)

        # VMA bounds: top, left, bottom, right, max_channels (each uint32)
        if pos + 20 > len(data):
            return None
        top = struct.unpack_from('>I', data, pos)[0]; pos += 4
        left = struct.unpack_from('>I', data, pos)[0]; pos += 4
        bottom = struct.unpack_from('>I', data, pos)[0]; pos += 4
        right = struct.unpack_from('>I', data, pos)[0]; pos += 4
        max_channels = struct.unpack_from('>I', data, pos)[0]; pos += 4

        canvas_w = right - left
        canvas_h = bottom - top
        if not (0 < canvas_w <= 16384 and 0 < canvas_h <= 16384):
            return None
        if max_channels > 200:
            return None

        # Iterate channel entries to find the first written channel
        best_data = None
        best_dims = None
        for ch_idx in range(max_channels + 2):
            if pos + 4 > vma_end:
                break
            is_written = struct.unpack_from('>I', data, pos)[0]
            pos += 4

            if is_written == 0:
                continue

            if pos + 4 > vma_end:
                break
            ch_length = struct.unpack_from('>I', data, pos)[0]
            pos += 4
            ch_end = pos + ch_length

            if ch_length <= 23 or ch_end > vma_end:
                pos = min(ch_end, vma_end)
                continue

            # Channel header: depth(4) + TLBR(4*4) + pixel_depth(2) + compression(1)
            ch_depth = struct.unpack_from('>I', data, pos)[0]
            ch_top = struct.unpack_from('>I', data, pos + 4)[0]
            ch_left = struct.unpack_from('>I', data, pos + 8)[0]
            ch_bottom = struct.unpack_from('>I', data, pos + 12)[0]
            ch_right = struct.unpack_from('>I', data, pos + 16)[0]
            _ch_pixel_depth = struct.unpack_from('>H', data, pos + 20)[0]
            ch_compression = data[pos + 22]

            ch_w = ch_right - ch_left
            ch_h = ch_bottom - ch_top
            img_start = pos + 23

            if (0 < ch_w <= 16384 and 0 < ch_h <= 16384 and
                    ch_depth in (8, 16) and ch_compression in (0, 1)):
                bpp = max(1, ch_depth // 8)
                ch_img_data = data[img_start:ch_end]
                extracted = self._extract_single_channel(
                    ch_img_data, ch_w, ch_h, bpp, ch_compression
                )
                if extracted is not None and best_data is None:
                    best_data = extracted
                    best_dims = (ch_w, ch_h, ch_depth)

            pos = min(ch_end, vma_end)

        if best_data is None or best_dims is None:
            return None

        ch_w, ch_h, ch_depth = best_dims
        tip = BrushTip(
            name=brush_name if brush_name else f"Brush {index + 1}",
            width=ch_w, height=ch_h, depth=ch_depth,
            channels=1,
            diameter=max(ch_w, ch_h), brush_type=2,
            image_data=best_data,
        )
        self._finalize_tip(tip)
        return tip

    def _try_parse_v6_simple(self, data: bytes, index: int) -> Optional[BrushTip]:
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

        channels = self._detect_channels_from_data(data, offset, width, height, depth)

        image_data = self._extract_image(
            data[offset:], width, height, depth, compression, channels
        )
        if image_data is None:
            return None

        tip = BrushTip(
            name=f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            channels=channels,
            diameter=max(width, height), brush_type=2,
            image_data=image_data,
        )
        self._finalize_tip(tip)
        return tip

    def _try_parse_v6_named(self, data: bytes, index: int) -> Optional[BrushTip]:
        if len(data) < 20:
            return None

        offset = 4
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

        offset += 1  # skip unknown byte

        spacing = 25
        if offset + 2 <= len(data):
            raw_spacing = struct.unpack_from('>H', data, offset)[0]
            if 1 <= raw_spacing <= 1000:
                spacing = raw_spacing

        result = self._find_bounds_in_data(data, offset)
        if result is None:
            return None

        bounds_offset, top, left, bottom, right, depth, compression, bounds_type = result
        width = right - left
        height = bottom - top

        if bounds_type == 'short':
            img_offset = bounds_offset + 8 + 2 + 1
        else:
            img_offset = bounds_offset + 16 + 2 + 1

        channels = self._detect_channels_from_data(
            data, img_offset, width, height, depth
        )

        image_data = self._extract_image(
            data[img_offset:], width, height, depth, compression, channels
        )
        if image_data is None and channels > 1:
            # Fallback to single channel
            image_data = self._extract_image(
                data[img_offset:], width, height, depth, compression, 1
            )
            channels = 1
        if image_data is None:
            return None

        tip = BrushTip(
            name=name if name else f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            channels=channels,
            diameter=max(width, height), brush_type=2,
            spacing=spacing, image_data=image_data,
        )
        self._finalize_tip(tip)
        return tip

    def _try_parse_v6_scan(self, data: bytes, index: int) -> Optional[BrushTip]:
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

        image_data = self._extract_image(
            data[img_offset:], width, height, depth, compression, 1
        )
        if image_data is None:
            return None

        tip = BrushTip(
            name=f"Brush {index + 1}",
            width=width, height=height, depth=depth,
            channels=1,
            diameter=max(width, height), brush_type=2,
            image_data=image_data,
        )
        self._finalize_tip(tip)
        return tip

    def _detect_channels_from_data(self, data: bytes, img_offset: int,
                                   width: int, height: int, depth: int) -> int:
        """Heuristic: estimate channel count from available data size."""
        bpp = max(1, depth // 8)
        one_ch = width * height * bpp
        available = len(data) - img_offset

        if one_ch <= 0:
            return 1
        if available >= one_ch * 4:
            return 4
        if available >= one_ch * 3:
            return 3
        return 1

    # ---------- Bounds / image extraction helpers ----------

    def _find_bounds_in_data(self, data: bytes, start: int) -> Optional[tuple]:
        end_u16 = min(start + 120, len(data) - 11)
        for offset in range(start, max(start, end_u16)):
            try:
                top, left, bottom, right = struct.unpack_from('>HHHH', data, offset)
            except struct.error:
                break
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
        for offset in range(start, max(start, end_u32)):
            try:
                top, left, bottom, right = struct.unpack_from('>IIII', data, offset)
            except struct.error:
                break
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
                       depth: int, compression: int,
                       channels: int = 1) -> Optional[bytes]:
        """Extract pixel data, optionally multi-channel (planar → interleaved)."""
        bpp = max(1, depth // 8)
        channel_size = width * height * bpp

        if channels == 1:
            return self._extract_single_channel(data, width, height, bpp, compression)

        # Multi-channel: stored as separate planes
        planes = []
        f = io.BytesIO(data)
        for ch in range(channels):
            remaining = len(data) - f.tell()
            if remaining < 4:
                break

            plane = self._extract_single_channel_from_stream(
                f, width, height, bpp, compression
            )
            if plane is None:
                if ch >= 1:
                    break
                return None
            planes.append(plane)

        if not planes:
            return None

        # Interleave: plane-separate → pixel-interleaved
        pixel_count = width * height
        num_ch = len(planes)
        result = bytearray(pixel_count * num_ch)
        for ch, plane in enumerate(planes):
            for px in range(min(pixel_count, len(plane))):
                result[px * num_ch + ch] = plane[px]

        return bytes(result)

    def _extract_single_channel(self, data: bytes, width: int, height: int,
                                bpp: int, compression: int) -> Optional[bytes]:
        expected = width * height * bpp

        if compression == 0:
            if len(data) < expected:
                return None
            return data[:expected]

        elif compression == 1:
            return self._decode_rle_from_bytes(data, width * bpp, height)

        return None

    def _extract_single_channel_from_stream(self, f: io.BytesIO, width: int,
                                            height: int, bpp: int,
                                            compression: int) -> Optional[bytes]:
        """Extract a single channel from an open BytesIO stream, advancing position."""
        expected = width * height * bpp

        if compression == 0:
            data = f.read(expected)
            return data if len(data) == expected else None

        elif compression == 1:
            try:
                scanline_sizes = [struct.unpack('>H', f.read(2))[0] for _ in range(height)]
            except struct.error:
                return None

            result = bytearray()
            row_width = width * bpp
            for sl_size in scanline_sizes:
                compressed = f.read(sl_size)
                if len(compressed) < sl_size:
                    compressed += b'\x00' * (sl_size - len(compressed))
                row = self._decode_packbits(compressed, row_width)
                result.extend(row)
                if len(row) < row_width:
                    result.extend(b'\x00' * (row_width - len(row)))

            return bytes(result[:expected])

        return None

    def _decode_rle_from_bytes(self, data: bytes, row_bytes: int,
                               height: int) -> Optional[bytes]:
        f = io.BytesIO(data)
        try:
            scanline_sizes = [struct.unpack('>H', f.read(2))[0] for _ in range(height)]
        except struct.error:
            return None

        result = bytearray()
        for sl_size in scanline_sizes:
            compressed = f.read(sl_size)
            if len(compressed) < sl_size:
                compressed += b'\x00' * (sl_size - len(compressed))
            row = self._decode_packbits(compressed, row_bytes)
            result.extend(row)
            if len(row) < row_bytes:
                result.extend(b'\x00' * (row_bytes - len(row)))

        return bytes(result[:row_bytes * height])

    def _finalize_tip(self, tip: BrushTip) -> None:
        pixel_count = tip.width * tip.height * tip.channels

        if tip.depth == 16:
            tip.image_data = self._convert_16_to_8(tip.image_data)
            tip.depth = 8
            pixel_count = tip.width * tip.height * tip.channels

        if len(tip.image_data) < pixel_count:
            tip.image_data += b'\x00' * (pixel_count - len(tip.image_data))
        tip.image_data = tip.image_data[:pixel_count]

    # ================================================================= #
    #  Conversion helpers                                                  #
    # ================================================================= #

    @staticmethod
    def _convert_16_to_8(data: bytes) -> bytes:
        result = bytearray(len(data) // 2)
        for i in range(0, len(data) - 1, 2):
            result[i // 2] = data[i]
        return bytes(result)

    @staticmethod
    def _generate_computed_image(size: int, roundness: int, angle: int, hardness: int) -> bytes:
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

    # ================================================================= #
    #  Grayscale extraction from multi-channel data                       #
    # ================================================================= #

    @staticmethod
    def get_grayscale(tip: BrushTip) -> bytes:
        """Return grayscale version. RGBA → uses alpha; RGB → luminance."""
        if tip.channels == 1:
            return tip.image_data

        pixel_count = tip.width * tip.height
        result = bytearray(pixel_count)
        ch = tip.channels
        data = tip.image_data

        if ch == 4:
            for px in range(pixel_count):
                idx = px * 4 + 3
                result[px] = data[idx] if idx < len(data) else 0
        elif ch == 3:
            for px in range(pixel_count):
                base = px * 3
                if base + 2 < len(data):
                    r, g, b = data[base], data[base + 1], data[base + 2]
                    result[px] = min(255, int(0.299 * r + 0.587 * g + 0.114 * b))
        else:
            for px in range(pixel_count):
                idx = px * ch
                result[px] = data[idx] if idx < len(data) else 0

        return bytes(result)


# ===================================================================== #
#  Convenience wrapper                                                   #
# ===================================================================== #

def parse_abr(filepath: str) -> Tuple[List[BrushTip], List[BrushPattern]]:
    """Parse an ABR file and return (brush_tips, patterns)."""
    parser = ABRParser(filepath=filepath)
    tips = parser.parse()
    return tips, parser.patterns
