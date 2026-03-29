# ABR Brush Importer — Krita Plugin

A [Krita](https://krita.org/) Python plugin that imports Adobe Photoshop `.abr`
brush files directly into Krita, with full support for brush dynamics, pressure
curves, spacing, scatter, jitter, and more.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
  - [Drop-folder (automatic)](#drop-folder-recommended--fully-automatic)
  - [Interactive dialog](#interactive-dialog)
  - [Import from a URL](#import-from-a-url-online-abr)
  - [Automatic Import settings](#automatic-import-settings-in-the-dialog)
- [Import options](#import-options)
- [Standalone converter](#standalone-converter-no-krita-required)
- [Running the tests](#running-the-tests)
- [Cache and settings locations](#cache-and-settings-locations)
- [Security notes](#security-notes)

---

## Features

- Parses ABR versions 1, 2, 6, 7, 9, and 10
- Exports brushes in three formats:
  - **`.gbr`** — GIMP Brush v2 (recognized by Krita as a brush tip)
  - **`.png`** — plain image of the brush tip
  - **`.kpp`** — Krita Preset (preserves dynamics: spacing, opacity, flow,
    scatter, jitter, pressure curves, smoothing, wet edges, …)
- **Best-match import** — automatically writes `.kpp` for brushes with
  dynamics and `.gbr` for simpler brushes
- **Automatic drop-folder** — place `.abr` files in a watched folder and
  they are imported on every Krita startup, or continuously in the background
- **Online ABR** — paste a URL pointing to a `.abr` file or a `.zip`
  archive; the plugin downloads, caches, and loads the brushes automatically
- **Import tracking** — an on-disk database skips files that have not
  changed since the last import
- All background work runs on a dedicated thread — Krita's UI is never blocked
- Live preview with per-brush metadata
- Batch import of all or selected brushes
- Exports embedded Photoshop patterns as PNG files

---

## Requirements

- Krita 5.x with Python scripting enabled
- Python 3.8+
- PyQt5 (bundled with Krita)

---

## Installation

### Linux (quick install)

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
   - **macOS**: `~/Library/Application Support/Krita/pykrita/`
   - **Windows**: `%APPDATA%\krita\pykrita\`
2. Create a sub-folder named `abr_brush_importer/` inside it.
3. Copy `abr_brush_importer.desktop` into the *pykrita* root.
4. Copy all `abr_brush_importer/*.py` files into the sub-folder.

### Enable in Krita

1. Open Krita.
2. Go to **Settings → Configure Krita → Python Plugin Manager**.
3. Tick **ABR Brush Importer** and click **OK**.
4. Restart Krita.

---

## Usage

### Drop-folder (recommended — fully automatic)

The simplest way to use the plugin: create a folder called `abr_brushes` inside
Krita's resource directory, drop your `.abr` files into it, and restart Krita.
The plugin scans this folder **automatically on every startup** and imports any
new or changed brushes — no dialog required.

| Platform | Drop folder |
|----------|-------------|
| Linux    | `~/.local/share/krita/abr_brushes/` |
| macOS    | `~/Library/Application Support/Krita/abr_brushes/` |
| Windows  | `%APPDATA%\krita\abr_brushes\` |

Imported brushes appear in the **Predefined Brush Tips** panel. Files that have
not changed since the last import are skipped automatically.

### Interactive dialog

Open the importer via **Tools → Scripts → Import ABR Brushes…**

1. Click **Open ABR File…** and select a `.abr` file.
2. Browse the brush list; click any brush to preview it.
3. Select the brushes you want (**Select All** / **Select None** as needed).
4. Choose output formats in the *Import Options* section.
5. Click **Import Selected**.

### Import from a URL (Online ABR)

1. Paste a URL into the **Online ABR** text box. Supported formats:
   - Direct `.abr` link: `https://example.com/my_brushes.abr`
   - `.zip` archive containing one or more `.abr` files: `https://example.com/brushpack.zip`
2. Click **Download** — a progress bar shows download status. If the archive
   contains multiple `.abr` files, a dialog lets you pick one.
3. The downloaded brushes load automatically; proceed as with a local file.
4. The file is **cached** locally; click **Force Refresh** to re-download.
5. Click **Clear Cache** to remove all cached downloads.

### Automatic Import settings (in the dialog)

The *Automatic Import* section of the dialog configures background importing:

| Setting | Description |
|---------|-------------|
| **Enable continuous watcher** | Imports new `.abr` files as soon as they appear in the watch folder, without restarting Krita |
| **Watch folder** | Custom folder to watch (leave blank to use the default drop folder) |
| **Include sub-folders** | Scan the watch folder recursively |
| **Import on Krita startup** | Run a scan automatically when Krita opens |
| **Refresh resources after import** | Notify Krita after import so new brushes appear without a manual resource refresh |
| **Scan Now** | Trigger a one-shot scan immediately |

Settings are saved automatically and restored on the next launch.

---

## Import options

| Option | Description |
|--------|-------------|
| Best match (recommended) | `.kpp` for brushes with dynamics, `.gbr` otherwise |
| Save as `.gbr` | Writes GIMP Brush v2 files (brush tip only) |
| Also save as `.png` | Writes a plain PNG image of the brush tip |
| Also save as `.kpp` | Writes a full Krita Preset preserving all dynamics |
| Export embedded patterns as PNG | Saves any Photoshop patterns embedded in the `.abr` file |
| Invert brush images | Inverts pixel values (useful if brushes appear inverted) |
| Enable pressure sensitivity | Adds a pressure→size curve to `.kpp` presets |

Imported brushes are written to `<krita-resources>/brushes/`. If they are not
visible immediately, go to **Settings → Manage Resources** or restart Krita.

---

## Standalone converter (no Krita required)

```bash
python3 standalone.py <file.abr> [output_dir]
```

Converts every brush in `file.abr` to `.gbr`, `.png`, and `.kpp` files and
writes them to `output_dir` (defaults to `./abr_output`). No Krita installation
is needed.

---

## Running the tests

The test suite runs with plain Python and has no external dependencies:

```bash
python3 test_plugin.py
```

---

## Cache and settings locations

All plugin data is stored under `<krita-resource-dir>/abr_importer_cache/`:

| File | Purpose |
|------|---------|
| `abr_import_db.json` | Tracks imported files (modification time, timestamp, errors) |
| `auto_import_settings.json` | Persistent auto-import configuration |
| `<hash>_<filename>` | Cached downloaded ABR and ZIP files |

| Platform | Resource directory |
|----------|--------------------|
| Linux    | `~/.local/share/krita/` |
| macOS    | `~/Library/Application Support/Krita/` |
| Windows  | `%APPDATA%\krita\` |

To free space, click **Clear Cache** in the plugin UI or delete the
`abr_importer_cache/` folder manually.

---

## Security notes

- Downloads are capped at **200 MB** by default to prevent runaway transfers.
- Only `.abr` files are extracted from zip archives; all other entries are
  ignored.
- Zip-slip path traversal attacks are blocked: extracted files are always placed
  directly inside the cache directory, regardless of the path stored in the
  archive.
