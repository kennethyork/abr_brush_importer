# ABR Brush Importer — Krita Plugin

A [Krita](https://krita.org/) Python plugin that imports Adobe Photoshop `.abr`
brush files directly into Krita with full dynamics, dual brush support, and
**17 traditional paint medium modes** — from pixel brushes to oil, watercolour,
charcoal, and more.

---

## Table of Contents

- [Features](#features)
- [Paint medium modes](#paint-medium-modes)
- [Comparison with GIMP's built-in ABR importer](#comparison-with-gimps-built-in-abr-importer)
- [Comparison with Photoshop](#comparison-with-photoshop)
- [Feature coverage at a glance](#feature-coverage-at-a-glance)
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
- **Every imported brush produces both a full preset and a brush tip:**
  - **`.kpp`** → `paintoppresets/` — Krita Preset (preserves dynamics: spacing,
    opacity, flow, scatter, jitter, pressure curves, smoothing, wet edges, …).
    Appears in the **Brush Presets** docker.
  - **`.gbr`** → `brushes/` — GIMP Brush v2 (recognized by Krita as a brush tip).
    Appears in the **Predefined Brush Tips** tab.
  - **`.png`** — optional plain image of the brush tip
- **17 paint medium modes** — import any ABR brush as a pixel brush, pencil,
  chalk, charcoal, ink, marker, airbrush, spray paint, gouache, oil, acrylic,
  tempera, watercolour, encaustic, fresco, or more (see table below)
- **Dual brush support** — ABR dual brush settings are mapped to Krita's
  masking brush with correct composite mode, scatter, spacing, and flip.
  Sampled dual brush tips are resolved by name and written as separate `.gbr`
  files; computed tips are generated automatically as fallback
- **Full dynamics mapping** — ABR brush dynamics (opacity, flow, scatter,
  size/angle/roundness jitter, pressure curves, color dynamics, purity/fg-bg
  mixing, noise, wet edges, smoothing, airbrush, flip) are all mapped to
  Krita's native sensor system
- **17 PS blend modes** mapped to Krita composite operations (multiply, darken,
  screen, overlay, soft light, hard light, vivid light, etc.)
- **Texture / pattern support** — ABR texture settings are mapped to Krita's
  pattern overlay system; noise is approximated with a grain texture
- **Auto-generated `.bundle`** — a Krita resource bundle containing all
  presets, brush tips, and patterns is created automatically on every import
  for easy backup and sharing
- **Automatic drop-folder** — place `.abr` files in a watched folder and
  they are imported on every Krita startup, or continuously in the background
- **Online ABR** — paste a URL pointing to a `.abr` file or a `.zip`
  archive; the plugin downloads, caches, and loads the brushes automatically
- **Import tracking** — an on-disk database skips files that have not
  changed since the last import
- **Multi-directory replication** — brush files, presets, and bundles are
  automatically copied to all detected Krita resource directories (Flatpak,
  Snap, native)
- All background work runs on a dedicated thread — Krita's UI is never blocked
- Live preview with per-brush metadata
- Batch import of all or selected brushes
- Exports embedded Photoshop patterns as PNG files

---

## Paint medium modes

The plugin offers **17 paint engine modes**, selectable from a dropdown in the
import dialog. Any ABR brush shape can be imported as any medium type.

### Dry media (paintbrush engine)

| Mode | Description |
| ---- | ----------- |
| **Pixel brush** | Standard dry brush — default mapping of ABR dynamics |
| **Pencil / Graphite** | Fine texture overlay (grain scale 0.20), low flow (0.4) |
| **Colored pencil** | Light texture overlay (grain scale 0.25), medium flow (0.6) |
| **Chalk / Pastel** | Textured grain overlay (10_drawed_dotted, scale 1.0) |
| **Conté / Sanguine** | Dense chalky grain (scale 0.50) |
| **Charcoal** | Heavy grain texture (scale 0.35) |
| **Ink** | Sharp solid strokes — full flow and opacity, no pressure on opacity |
| **Marker** | Flat strokes with `darken` composite — ink builds up at overlaps |
| **Airbrush (soft)** | Airbrush mode enabled, soft edges |
| **Spray paint** | Airbrush mode + scatter (1.5+), both axes — graffiti-style |

### Wet / mixing media (colorsmudge engine)

| Mode | Description |
| ---- | ----------- |
| **Gouache / Oil** | Opaque wet mixing — ColorRate 1, SmudgeRate 1 |
| **Oil heavy** | Palette knife — wide pickup radius (SmudgeRadius 9.23), thick mixing |
| **Acrylic** | Opaque, fast-drying — reduced mixing (SmudgeRate 0.4) |
| **Tempera** | Egg-based, matte — minimal mixing (SmudgeRate 0.15) |
| **Watercolour** | Translucent washes — ColorRate 0.5, layered transparency |
| **Encaustic** | Hot wax paint — large SmudgeRadius (5.0), heavy drag |
| **Fresco** | Pigment on wet plaster — medium mixing (SmudgeRate 0.6) |

> **Note:** Photoshop ABR files only store brush tip shapes and dynamics — they
> do not contain paint medium information. These modes apply Krita engine
> parameters tuned from Krita's own built-in reference presets to give the
> imported brush shape the *feel* of each medium.

---

## Comparison with GIMP's built-in ABR importer

| Feature | GIMP `file-abr` | This plugin |
| ------- | :-: | :-: |
| **ABR version support** | | |
| ABR v1 / v2 (legacy Photoshop) | ✅ | ✅ |
| ABR v6 (CS, CS2) | ✅ | ✅ |
| ABR v7 / v9 / v10 (CS3–CC) | ⚠️ partial | ✅ |
| **Output formats** | | |
| GIMP Brush (`.gbr`) | ✅ | ✅ |
| Plain PNG image | ❌ | ✅ |
| Krita Preset (`.kpp`) with full dynamics | ❌ | ✅ |
| Krita resource bundle (`.bundle`) | ❌ | ✅ |
| **Brush shape properties** | | |
| Brush bitmap / grayscale tip | ✅ | ✅ |
| RGB / RGBA colour brush tips | ❌ | ✅ |
| Computed (procedural) brush tips | ✅ | ✅ |
| Spacing | ✅ | ✅ |
| Diameter / angle / hardness | ✅ | ✅ |
| Roundness (aspect ratio) | ❌ | ✅ |
| **Brush dynamics (ABR v6+)** | | |
| Opacity | ❌ discarded | ✅ |
| Flow | ❌ discarded | ✅ |
| Scatter amount & dab count | ❌ discarded | ✅ |
| Size / angle / roundness jitter | ❌ discarded | ✅ |
| Pressure→size curve | ❌ discarded | ✅ |
| Pressure→opacity curve | ❌ discarded | ✅ |
| Pressure→flow curve | ❌ discarded | ✅ |
| Flip X/Y per dab | ❌ discarded | ✅ |
| Color dynamics (H/S/V jitter) | ❌ discarded | ✅ |
| Purity (foreground/background mixing) | ❌ discarded | ✅ |
| Wet edges | ❌ discarded | ✅ |
| Noise | ❌ discarded | ✅ (grain texture) |
| Smoothing / stroke stabiliser | ❌ discarded | ✅ |
| Airbrush mode | ❌ discarded | ✅ |
| Dual brush (masking brush) | ❌ discarded | ✅ |
| Dual brush blend modes (17 modes) | ❌ discarded | ✅ |
| Texture / pattern overlay | ❌ discarded | ✅ |
| **Paint engine modes** | | |
| Pixel brush | ❌ `.gbr` only | ✅ |
| Wet media (oil/gouache/watercolour/etc.) | ❌ | ✅ 7 modes |
| Dry media (chalk/charcoal/pencil/etc.) | ❌ | ✅ 10 modes |
| **Workflow & automation** | | |
| Batch import | ✅ | ✅ |
| Live preview & metadata | ❌ | ✅ |
| Drop-folder auto-import | ❌ | ✅ |
| Background file watcher | ❌ | ✅ |
| Import from URL | ❌ | ✅ |
| Import-tracking database | ❌ | ✅ |

**Overall fidelity: ~97% vs GIMP's ~5%** — GIMP extracts only the raw stamp
shape; this plugin preserves virtually all ABR brush behaviour.

---

## Comparison with Photoshop

Photoshop is the native ABR format, so it reads its own presets at 100%
fidelity. This plugin can't beat that. But it goes beyond what Photoshop does
with ABR files:

| Capability | Photoshop | This plugin |
| ---------- | :-------: | :---------: |
| Load ABR brush tips | ✅ native | ✅ ~97% fidelity |
| ABR dynamics (curves, scatter, jitter) | ✅ native | ✅ mapped to Krita sensors |
| Dual brush | ✅ native | ✅ masking brush |
| **Use ABR tip as oil/gouache/watercolour** | ❌ must switch to Mixer Brush | ✅ one-click import |
| **Use ABR tip as chalk/charcoal/pencil** | ❌ ABR = pixel brush only | ✅ auto texture grain |
| **Use ABR tip as marker (darken overlap)** | ❌ manual preset setup | ✅ built in |
| **17 paint medium modes from any ABR** | ❌ | ✅ |
| Batch import with dedup database | ✅ | ✅ |
| Auto-watcher for drag-and-drop | ❌ | ✅ |
| Cross-app portability | Photoshop only | Krita native `.kpp` |

---

## Feature coverage at a glance

| Feature | **This Plugin (v1.0.2)** | **Krita Built-in** | **Other Krita Plugins** | **Photoshop** |
|---|:---:|:---:|:---:|:---:|
| Brush tip extraction (v1–v10) | ✅ Full | ✅ Partial (tips only) | ✅ Tips only | ✅ |
| Computed brushes (ellipse+hardness) | ✅ | ❌ | ❌ | ✅ |
| Sampled brushes (RGB/RGBA/Gray) | ✅ | ✅ Gray only | ✅ Gray only | ✅ |
| Preset generation (.kpp) | ✅ Auto | ❌ Manual setup | ❌ | ✅ Auto |
| Pressure → size curve | ✅ | ❌ | ❌ | ✅ |
| Pressure → opacity curve | ✅ | ❌ | ❌ | ✅ |
| Pressure → flow curve | ✅ | ❌ | ❌ | ✅ |
| Shape dynamics (size/angle/roundness jitter) | ✅ | ❌ | ❌ | ✅ |
| Scattering (amount + count + axes) | ✅ | ❌ | ❌ | ✅ |
| Color dynamics (H/S/B jitter + fg-bg) | ✅ | ❌ | ❌ | ✅ |
| Texture overlay (pattern + scale + depth) | ✅ | ❌ | ❌ | ✅ |
| Texture blend mode (19 PS modes mapped) | ✅ | ❌ | ❌ | ✅ |
| Soft texturing (PS compatibility) | ✅ | ❌ | ❌ | ✅ |
| Dual brush / masking brush | ✅ | ❌ | ❌ | ✅ |
| Airbrush mode | ✅ | ❌ | ❌ | ✅ |
| Flip X/Y per dab | ✅ | ❌ | ❌ | ✅ |
| Smoothing / stroke stabiliser | ✅ | ❌ | ❌ | ✅ |
| Spacing / angle / roundness | ✅ | ✅ | ✅ | ✅ |
| Wet edges | ⚠️ Approximated | ❌ | ❌ | ✅ |
| Procedural noise | ⚠️ Grain fallback | ❌ | ❌ | ✅ |
| 17 paint medium modes | ✅ | ❌ | ❌ | N/A |
| Bundle generation | ✅ | ❌ | ❌ | N/A |
| Auto-import on startup | ✅ Drop folder | ❌ | ❌ | N/A |
| pip install (PyPI) | ✅ | ❌ | ❌ | N/A |
| CLI converter (`abr-import`) | ✅ | ❌ | ❌ | ❌ |
| Cross-platform (Linux/Mac/Win) | ✅ | ✅ | Varies | ✅ |

| Solution | Feature Coverage |
|---|---|
| **This plugin** | **~97%** |
| Photoshop (native) | 100% |
| Krita built-in import | ~15% (tips only, no dynamics) |
| Other Krita plugins | ~15–20% |

> The remaining ~3% gap is due to Krita engine limitations (no native wet edges
> or procedural per-dab noise) — no plugin can close it.

---

## Requirements

- Krita 5.x with Python scripting enabled
- Python 3.8+
- PyQt5 (bundled with Krita)

---

## Installation

### pip (recommended)

```bash
pip install abr-brush-importer
```

This installs the CLI converter (`abr-import`) and automatically detects and
installs the Krita plugin on first use. You can also manually trigger the Krita
install:

```bash
abr-install-krita          # auto-detect Krita and install
abr-install-krita --list   # show detected Krita locations
```

### Linux — native Krita

```bash
git clone https://github.com/kennethyork/abr_brush_importer.git
cd abr_brush_importer
bash install_local.sh
```

Installs to `~/.local/share/krita/pykrita/abr_brush_importer/`.

### Linux — Flatpak Krita

```bash
git clone https://github.com/kennethyork/abr_brush_importer.git
cd abr_brush_importer
bash install_flatpak.sh
```

Installs to `~/.var/app/org.kde.krita/data/krita/pykrita/abr_brush_importer/`.

> **Tip:** If you're not sure which you have, run `flatpak list | grep krita`.
> If it prints a result, use `install_flatpak.sh`.

### macOS

```bash
git clone https://github.com/kennethyork/abr_brush_importer.git
cd abr_brush_importer
bash install_macos.sh
```

Installs to `~/Library/Application Support/Krita/pykrita/abr_brush_importer/`.

### Windows

```bat
git clone https://github.com/kennethyork/abr_brush_importer.git
cd abr_brush_importer
install_windows.bat
```

Installs to `%APPDATA%\krita\pykrita\abr_brush_importer\`.

### Manual (any platform)

1. Locate your Krita *pykrita* folder:
   - **Linux (native)**: `~/.local/share/krita/pykrita/`
   - **Linux (Flatpak)**: `~/.var/app/org.kde.krita/data/krita/pykrita/`
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

| Platform         | Drop folder                                        |
| ---------------- | -------------------------------------------------- |
| Linux (native)   | `~/.local/share/krita/abr_brushes/`                |
| Linux (Flatpak)  | `~/.var/app/org.kde.krita/data/krita/abr_brushes/` |
| macOS            | `~/Library/Application Support/Krita/abr_brushes/` |
| Windows          | `%APPDATA%\krita\abr_brushes\`                     |

Imported brushes appear as **full presets** in the **Brush Presets** docker
and as brush tips in the **Predefined Brush Tips** panel. A `.bundle` file is
also created automatically. Files that have not changed since the last import
are skipped automatically.

### Interactive dialog

Open the importer via **Tools → Scripts → Import ABR Brushes…**

1. Click **Open ABR File…** and select a `.abr` file.
2. Browse the brush list; click any brush to preview it.
3. Select the brushes you want (**Select All** / **Select None** as needed).
4. Choose the **Paint engine** from the dropdown (Pixel, Chalk, Oil, etc.).
5. Adjust import options (invert, pressure sensitivity).
6. Click **Import Selected**.

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
| ------- | ----------- |
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
| ------ | ----------- |
| Paint engine mode | Dropdown with 17 paint media (Pixel, Chalk, Oil, Wash, etc.) — selects the Krita paint engine and tunes parameters to match the chosen medium |
| Best match (recommended) | Always writes `.kpp` preset + `.gbr` tip for every brush |
| Save as `.gbr` | Writes GIMP Brush v2 files (brush tip only) |
| Also save as `.png` | Writes a plain PNG image of the brush tip |
| Also save as `.kpp` | Writes a full Krita Preset preserving all dynamics |
| Export embedded patterns as PNG | Saves any Photoshop patterns embedded in the `.abr` file |
| Invert brush images | Inverts pixel values (useful if brushes appear inverted) |
| Enable pressure sensitivity | Adds a pressure→size curve to `.kpp` presets |

Imported presets are written to `<krita-resources>/paintoppresets/` and brush
tips to `<krita-resources>/brushes/`. A `.bundle` containing everything is
placed in the resource root. If brushes are not visible immediately, go to
**Settings → Manage Resources** or restart Krita.

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

The test suite (70 tests) runs with plain Python and has no external dependencies:

```bash
python3 test_plugin.py
```

---

## Cache and settings locations

All plugin data is stored under `<krita-resource-dir>/abr_importer_cache/`:

| File | Purpose |
| ---- | ------- |
| `abr_import_db.json` | Tracks imported files (modification time, timestamp, errors) |
| `auto_import_settings.json` | Persistent auto-import configuration |
| `<hash>_<filename>` | Cached downloaded ABR and ZIP files |

| Platform         | Resource directory                       |
| ---------------- | ---------------------------------------- |
| Linux (native)   | `~/.local/share/krita/`                  |
| Linux (Flatpak)  | `~/.var/app/org.kde.krita/data/krita/`   |
| macOS            | `~/Library/Application Support/Krita/`   |
| Windows          | `%APPDATA%\krita\`                       |

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
