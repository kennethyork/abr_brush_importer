# ABR Brush Importer — Krita Plugin

A [Krita](https://krita.org/) Python plugin that imports Adobe Photoshop `.abr`
brush files directly into Krita, with full support for brush dynamics, pressure
curves, spacing, scatter, jitter, and more.

---

## Table of Contents

- [Features](#features)
- [Comparison with GIMP's built-in ABR importer](#comparison-with-gimps-built-in-abr-importer)
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
- **Auto-generated `.bundle`** — a Krita resource bundle containing all
  presets, brush tips, and patterns is created automatically on every import
  for easy backup and sharing
- **Best-match import** — always writes `.kpp` + `.gbr`; the preset
  automatically maps ABR dynamics to Krita equivalents
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

## Comparison with GIMP's built-in ABR importer

GIMP ships a built-in ABR importer (`file-abr`) that turns ABR brush shapes
into GIMP Brush (`.gbr`) files.  It handles the most common ABR versions and
extracts the raw brush bitmap — but it stops there.  Every piece of
*dynamic* information stored in the ABR file is silently thrown away.

The table below shows the full feature gap.

| Feature | GIMP `file-abr` | This Krita plugin |
| ------- | :-: | :-: |
| **ABR version support** | | |
| ABR v1 / v2 (legacy Photoshop) | ✅ | ✅ |
| ABR v6 (CS, CS2) | ✅ | ✅ |
| ABR v7 / v9 / v10 (CS3–CC) | ⚠️ partial | ✅ |
| **Output formats** | | |
| GIMP Brush (`.gbr`) | ✅ | ✅ |
| Plain PNG image | ❌ | ✅ |
| Krita Preset (`.kpp`) with full dynamics | ❌ | ✅ |
| **Brush shape properties** | | |
| Brush bitmap / grayscale tip | ✅ | ✅ |
| RGB / RGBA colour brush tips | ❌ | ✅ |
| Computed (procedural) brush tips | ✅ | ✅ |
| Spacing | ✅ | ✅ |
| Diameter / angle / hardness | ✅ | ✅ |
| Roundness (aspect ratio) | ❌ | ✅ |
| **Brush dynamics (ABR v6+)** | | |
| Opacity | ❌ discarded | ✅ preserved in `.kpp` |
| Flow | ❌ discarded | ✅ preserved in `.kpp` |
| Scatter amount & dab count | ❌ discarded | ✅ preserved in `.kpp` |
| Size jitter | ❌ discarded | ✅ preserved in `.kpp` |
| Angle jitter | ❌ discarded | ✅ preserved in `.kpp` |
| Roundness jitter | ❌ discarded | ✅ preserved in `.kpp` |
| Pressure→size curve | ❌ discarded | ✅ preserved in `.kpp` |
| Pressure→opacity curve | ❌ discarded | ✅ preserved in `.kpp` |
| Pressure→flow curve | ❌ discarded | ✅ preserved in `.kpp` |
| Wet edges | ❌ discarded | ✅ preserved in `.kpp` |
| Smoothing / stroke stabiliser | ❌ discarded | ✅ preserved in `.kpp` |
| Dual brush | ❌ discarded | ✅ tip index preserved |
| **Embedded content** | | |
| Embedded Photoshop patterns (`patt` blocks) | ❌ | ✅ exported as PNG |
| **Workflow & automation** | | |
| Batch import of entire ABR file | ✅ | ✅ |
| Live preview & per-brush metadata | ❌ | ✅ |
| Drop-folder / zero-config auto-import | ❌ | ✅ |
| Background file watcher (no restart needed) | ❌ | ✅ |
| Import from URL (`.abr` or `.zip`) | ❌ | ✅ |
| Import-tracking database (skip unchanged files) | ❌ | ✅ |

> **Legend** — ✅ supported  ⚠️ limited / partial  ❌ not supported

### Why does this matter?

When you open an ABR file in GIMP you lose almost all of the brushwork the
original artist configured: the scatter that gives a grass brush its randomness,
the pressure curve that makes an ink brush taper naturally, the flow that
controls ink build-up.  The resulting `.gbr` is just the raw stamp shape.

This plugin reads the same ABR data but writes it into Krita's `.kpp` preset
format, which *has* native equivalents for every one of those dynamics.  The
brush you import into Krita behaves the way it was designed to behave.

---

## Requirements

- Krita 5.x with Python scripting enabled
- Python 3.8+
- PyQt5 (bundled with Krita)

---

## Installation

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

The test suite runs with plain Python and has no external dependencies:

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
