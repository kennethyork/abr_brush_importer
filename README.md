# ABR Brush Importer — Krita Plugin

A [Krita](https://krita.org/) Python plugin that imports Adobe Photoshop `.abr`
brush files directly into Krita, preserving brush dynamics, pressure curves,
spacing, scatter, jitter, and more.

---

## Features

- Parses ABR versions 1, 2, 6, 7, 9, 10
- Exports brushes as:
  - **`.gbr`** — GIMP Brush v2 (Krita recognises these as brush tips)
  - **`.png`** — plain image of the brush tip
  - **`.kpp`** — Krita Preset (preserves dynamics: spacing, opacity, flow,
    scatter, jitter, pressure curves, smoothing, wet edges, …)
- **Online ABR** — paste a URL to a `.abr` file or a `.zip` archive containing
  `.abr` files; the plugin downloads, caches, and loads the brushes
  automatically — no manual downloading required.
- Caches downloaded files in the Krita resource directory to avoid redundant
  network requests.

---

## Installation

### Linux (recommended)

```bash
git clone https://github.com/kennethyork/abr_brush_importer.git
cd abr_brush_importer
bash install.sh
```

The script copies all plugin files to
`~/.local/share/krita/pykrita/abr_brush_importer/`.

### Manual (any platform)

1. Locate your Krita *pykrita* folder:
   - **Linux**: `~/.local/share/krita/pykrita/`
   - **macOS**: `~/Library/Application Support/krita/pykrita/`
   - **Windows**: `%APPDATA%\krita\pykrita\`
2. Create a sub-folder `abr_brush_importer/` inside it.
3. Copy `abr_brush_importer.desktop` into the *pykrita* root.
4. Copy all `abr_brush_importer/*.py` files into the sub-folder.

### Enable in Krita

1. Open Krita.
2. Go to **Settings → Configure Krita → Python Plugin Manager**.
3. Enable **ABR Brush Importer**.
4. Restart Krita.

---

## Usage

Open the importer via **Tools → Scripts → Import ABR Brushes…**

### Import from a local file

1. Click **Open ABR File…** and select a `.abr` file.
2. Browse the brush list; click any brush to preview it.
3. Select the brushes you want (use **Select All** / **Select None** as needed).
4. Choose output formats in the *Import Options* section.
5. Click **Import Selected**.

### Import from a URL (Online ABR)

1. Paste a URL into the **Online ABR** text box.  
   Supported URL types:
   - Direct `.abr` link: `https://example.com/my_brushes.abr`
   - `.zip` archive containing `.abr` files: `https://example.com/brushpack.zip`
2. Click **Download**.  
   - A progress bar shows download progress.
   - If the archive contains multiple `.abr` files, a dialog lets you choose one.
3. The downloaded brushes are loaded automatically — proceed as with a local
   file (select, choose format, import).
4. The file is **cached** locally; subsequent downloads of the same URL skip the
   network request.  Use **Force Refresh** to re-download regardless.
5. Click **Clear Cache** to delete all cached downloads.

### Import options

| Option | Description |
|--------|-------------|
| Save as .gbr | Writes GIMP Brush v2 files (brush tip only) |
| Also save as .png | Writes a plain PNG image of the brush tip |
| Also save as .kpp | Writes a full Krita Preset preserving dynamics |
| Export embedded patterns as PNG | Saves any embedded Photoshop patterns |
| Invert brush images | Inverts pixel values (use if brushes appear inverted) |
| Enable pressure sensitivity | Adds a pressure→size curve to `.kpp` presets |

Imported brushes land in `<krita-resources>/brushes/`.  
Restart Krita or go to **Settings → Manage Resources** to see them in the
*Predefined* brush tab.

---

## Standalone converter (no Krita required)

```bash
python3 standalone.py <file.abr> [output_dir]
```

Exports every brush in `file.abr` as `.gbr`, `.png`, and `.kpp` files into
`output_dir` (defaults to `./abr_output`).

---

## Running the tests

Tests run outside Krita with no additional dependencies:

```bash
python3 test_plugin.py
```

---

## Cache location

Downloaded files are stored in a `abr_importer_cache/` sub-folder inside
Krita's writable resource directory:

| Platform | Default path |
|----------|-------------|
| Linux | `~/.local/share/krita/abr_importer_cache/` |
| macOS | `~/Library/Application Support/krita/abr_importer_cache/` |
| Windows | `%APPDATA%\krita\abr_importer_cache\` |

Use **Clear Cache** in the plugin UI or delete the folder manually to free space.

---

## Security notes

- Downloads are limited to **200 MB** by default to prevent runaway transfers.
- Only `.abr` files are extracted from zip archives; all other entries are
  ignored.
- Zip-slip path traversal attacks are blocked: extracted files are always placed
  directly inside the cache directory, regardless of the path stored in the
  archive.
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
