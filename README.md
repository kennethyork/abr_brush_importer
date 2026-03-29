# ABR Brush Importer for Krita

Import Adobe Photoshop `.abr` brush files directly into Krita — no manual
downloading or managing of `.gbr`/`.kpp` files required.

## Features

- Parses `.abr` files (versions 1, 2, 6, 7, 9, 10)
- **Best-match import**: automatically saves a `.kpp` Krita Preset for brushes
  that carry dynamics (spacing, scatter, jitter, pressure curves…), or a plain
  `.gbr` brush tip for simpler brushes
- Brush files are written straight into Krita's resource folder — they show up
  in the *Predefined Brush Tips* panel immediately (or after a quick resource
  refresh)
- Live preview with per-brush metadata
- Batch import of all or selected brushes
- Embedded pattern export

## Installation

### Quick install (Linux)

```bash
bash install.sh
```

### Manual install

Copy the contents of the `abr_brush_importer/` folder into Krita's plugin
directory:

| OS | Path |
|----|------|
| Linux | `~/.local/share/krita/pykrita/abr_brush_importer/` |
| macOS | `~/Library/Application Support/Krita/pykrita/abr_brush_importer/` |
| Windows | `%APPDATA%\krita\pykrita\abr_brush_importer\` |

Also copy `abr_brush_importer.desktop` into the parent `pykrita/` folder.

## Enable the plugin in Krita

1. Open Krita.
2. Go to **Settings → Configure Krita → Python Plugin Manager**.
3. Tick **ABR Brush Importer**.
4. Click **OK** and restart Krita.

## Importing brushes

1. In Krita, open **Tools → Scripts → Import ABR Brushes…**
2. Click **Open ABR File…** and select your `.abr` file.
3. The brush list populates with thumbnails.  Select the brushes you want
   (all are selected by default).
4. Leave **Best match (recommended)** selected — the plugin will choose the
   right format for each brush automatically.
5. Click **Import Selected**.

The brushes are saved to Krita's resource folder automatically.  They will
appear in the **Predefined Brush Tips** panel after Krita refreshes its
resources.  If they are not visible immediately, go to
**Settings → Manage Resources** or restart Krita.

## Advanced options

Switch to **Advanced (choose formats)** in the Import Options panel to control
the output format manually:

| Option | Description |
|--------|-------------|
| Save as `.gbr` | Plain GIMP Brush tip (Krita can use these as brush tips) |
| Also save as `.png` | Raw brush image |
| Also save as `.kpp` | Full Krita Preset — preserves dynamics, pressure curves, scatter, jitter, smoothing |

## Standalone converter (no Krita required)

Convert `.abr` files from the command line:

```bash
python3 standalone.py my_brushes.abr [output_dir]
```

The resulting `.gbr`/`.kpp` files can be copied to Krita's brushes folder
manually.

## Supported ABR versions

ABR v1, v2, v6, v7, v9, v10 (and later revisions of v6+).

## Requirements

- Krita 5.x with Python scripting enabled
- Python 3.8+
- PyQt5 (bundled with Krita)
