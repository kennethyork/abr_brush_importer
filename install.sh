#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Install ABR Brush Importer plugin for Krita
# ──────────────────────────────────────────────────────────────
set -e

KRITA_PYKRITA="$HOME/.local/share/krita/pykrita"

echo "╔══════════════════════════════════════════╗"
echo "║   ABR Brush Importer — Krita Plugin      ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Installing to: $KRITA_PYKRITA"
echo ""

# Create target directories
mkdir -p "$KRITA_PYKRITA/abr_brush_importer"

# Copy the .desktop manifest (sits alongside the package)
cp abr_brush_importer.desktop "$KRITA_PYKRITA/"

# Copy the Python package
cp abr_brush_importer/__init__.py      "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/abr_parser.py    "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/gbr_writer.py    "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/kpp_writer.py    "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/importer_dialog.py "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/kpp_writer.py    "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/net_utils.py     "$KRITA_PYKRITA/abr_brush_importer/"
cp abr_brush_importer/utils.py         "$KRITA_PYKRITA/abr_brush_importer/"

echo "✓ Files copied."
echo ""
echo "Next steps:"
echo "  1. Open Krita"
echo "  2. Go to  Settings → Configure Krita → Python Plugin Manager"
echo "  3. Enable 'ABR Brush Importer'"
echo "  4. Restart Krita"
echo "  5. Use it via  Tools → Scripts → Import ABR Brushes…"
echo ""
echo "Done!"
