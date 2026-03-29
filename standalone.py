#!/usr/bin/env python3
"""
Standalone ABR → GBR/PNG converter.

Use this outside of Krita to batch-convert .abr files.
The resulting .gbr files can be dropped into Krita's brushes folder.

Usage:
    python3 standalone.py <file.abr> [output_dir]

If output_dir is omitted, files are saved next to the ABR file.
"""

import sys
import os

# Allow running from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from abr_brush_importer.abr_parser import parse_abr
from abr_brush_importer.gbr_writer import write_gbr, write_png
from abr_brush_importer.kpp_writer import write_kpp


def _sanitize(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:100] if safe else "brush"


def main() -> None:
    if len(sys.argv) < 2:
        print("ABR Brush Converter — converts Photoshop .abr to .gbr + .png")
        print()
        print("Usage:  python3 standalone.py <file.abr> [output_dir]")
        sys.exit(1)

    abr_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(abr_path))

    if not os.path.isfile(abr_path):
        print(f"Error: file not found: {abr_path}")
        sys.exit(1)

    print(f"Parsing: {abr_path}")

    try:
        brushes, patterns = parse_abr(abr_path)
    except Exception as exc:
        print(f"Error parsing ABR file: {exc}")
        sys.exit(1)

    print(f"Found {len(brushes)} brush(es), {len(patterns)} pattern(s)")

    if not brushes:
        print("No brushes were extracted. The file may use an unsupported variant.")
        sys.exit(0)

    os.makedirs(output_dir, exist_ok=True)

    for i, tip in enumerate(brushes):
        name = tip.name or f"brush_{i + 1}"
        safe = _sanitize(name)
        if not safe:
            safe = f"brush_{i + 1}"

        gbr_path = os.path.join(output_dir, f"{safe}.gbr")
        png_path = os.path.join(output_dir, f"{safe}.png")
        kpp_path = os.path.join(output_dir, f"{safe}.kpp")

        from abr_brush_importer.abr_parser import ABRParser
        gray_data = ABRParser.get_grayscale(tip) if tip.channels > 1 else tip.image_data
        write_gbr(gbr_path, name, tip.width, tip.height, gray_data, tip.spacing)
        write_png(png_path, tip.width, tip.height, tip.image_data, channels=tip.channels)
        write_kpp(kpp_path, tip)

        print(f"  [{i + 1}/{len(brushes)}] {name} ({tip.width}×{tip.height})")

    if patterns:
        print(f"\nExporting {len(patterns)} pattern(s)…")
        for pat in patterns:
            safe = _sanitize(pat.name or "pattern")
            if not safe:
                safe = "pattern"
            pat_path = os.path.join(output_dir, f"{safe}_pattern.png")
            write_png(pat_path, pat.width, pat.height,
                      pat.image_data, channels=pat.channels)
            print(f"  Pattern: {pat.name} ({pat.width}×{pat.height})")

    print(f"\nDone! Files saved to: {output_dir}")
    print("Copy the .gbr/.kpp files to ~/.local/share/krita/brushes/ and restart Krita.")


if __name__ == "__main__":
    main()
