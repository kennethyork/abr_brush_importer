"""
Qt dialog for importing ABR brush files into Krita.

Provides:
  - File browser to select .abr files
  - Thumbnail list with brush names and dimensions
  - Large preview pane with metadata
  - Options: Best-match (recommended) or advanced format selection
  - Batch import directly into Krita's resource folder — no manual
    file handling needed
  - Automatic Import settings: configure a watch folder, startup import,
    and a continuous background watcher
"""

import os
import time as _time
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QCheckBox,
    QProgressBar, QGroupBox, QMessageBox, QSplitter,
    QAbstractItemView, QRadioButton, QButtonGroup, QWidget,
    QLineEdit, QComboBox,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon

from .abr_parser import ABRParser, BrushTip, BrushPattern
from .bundle_writer import write_bundle
from .gbr_writer import write_gbr, write_png
from .kpp_writer import write_kpp
from .krita_resource_db import register_resources
from .utils import _sanitize, _unique, _choose_format, _friendly_name, brushes_dest, patterns_dest, paintoppresets_dest
from .auto_import import AutoImportSettings, scan_and_import
from .import_db import ImportDB
from .import_pipeline import ImportOptions


# ------------------------------------------------------------------ #
#  Helper — BrushTip -> QImage / QIcon                                 #
# ------------------------------------------------------------------ #

def _tip_to_qimage(tip: BrushTip) -> QImage:
    """Convert a BrushTip to a QImage for display.

    Handles grayscale (1ch), RGB (3ch), and RGBA (4ch) brush tips.
    For grayscale: inverts so brush shape is dark on white.
    For RGBA: composites over white background.
    """
    if tip.width <= 0 or tip.height <= 0:
        return QImage()

    pixel_count = tip.width * tip.height

    if tip.channels == 4:
        expected = pixel_count * 4
        if len(tip.image_data) < expected:
            return QImage()
        # Composite RGBA over white for preview
        data = tip.image_data
        rgb_buf = bytearray(pixel_count * 4)  # RGBA for QImage
        for px in range(pixel_count):
            base = px * 4
            r, g, b, a = data[base], data[base+1], data[base+2], data[base+3]
            af = a / 255.0
            rgb_buf[px*4]   = int(r * af + 255 * (1 - af))
            rgb_buf[px*4+1] = int(g * af + 255 * (1 - af))
            rgb_buf[px*4+2] = int(b * af + 255 * (1 - af))
            rgb_buf[px*4+3] = 255
        img = QImage(bytes(rgb_buf), tip.width, tip.height,
                     tip.width * 4, QImage.Format_RGBA8888)
        return img.copy()
    elif tip.channels == 3:
        expected = pixel_count * 3
        if len(tip.image_data) < expected:
            return QImage()
        # Pad RGB to RGBA with full alpha for QImage
        data = tip.image_data
        rgba_buf = bytearray(pixel_count * 4)
        for px in range(pixel_count):
            base = px * 3
            rgba_buf[px*4]   = data[base]
            rgba_buf[px*4+1] = data[base+1]
            rgba_buf[px*4+2] = data[base+2]
            rgba_buf[px*4+3] = 255
        img = QImage(bytes(rgba_buf), tip.width, tip.height,
                     tip.width * 4, QImage.Format_RGBA8888)
        return img.copy()
    else:
        if len(tip.image_data) < pixel_count:
            return QImage()
        inverted = bytes(255 - b for b in tip.image_data[:pixel_count])
        img = QImage(inverted, tip.width, tip.height, tip.width,
                     QImage.Format_Grayscale8)
        return img.copy()


def _tip_to_icon(tip: BrushTip, icon_size: int = 48) -> QIcon:
    """Create a QIcon thumbnail from a BrushTip."""
    img = _tip_to_qimage(tip)
    if img.isNull():
        return QIcon()
    pix = QPixmap.fromImage(img).scaled(
        icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    return QIcon(pix)


# ------------------------------------------------------------------ #
#  Preview widget                                                      #
# ------------------------------------------------------------------ #

class BrushPreviewWidget(QLabel):
    """Shows a scaled-up preview of the selected brush tip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel { background-color: #ffffff; border: 1px solid #aaa; }"
        )
        self.setText("Select a brush to preview")

    def show_brush(self, tip: BrushTip) -> None:
        img = _tip_to_qimage(tip)
        if img.isNull():
            self.setText("(no preview available)")
            return

        size = self.size()
        scaled = QPixmap.fromImage(img).scaled(
            size.width() - 10, size.height() - 10,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)


# ------------------------------------------------------------------ #
#  Main dialog                                                         #
# ------------------------------------------------------------------ #

class ABRImporterDialog(QDialog):
    """Import dialog for ABR brush files."""

    def __init__(self, resource_dir: str, parent=None, extra_resource_dirs=None):
        super().__init__(parent)
        self.resource_dir = resource_dir
        self.extra_resource_dirs = extra_resource_dirs or []
        self.brushes: list = []
        self.patterns: list = []

        self.setWindowTitle("ABR Brush Importer")
        self.setMinimumSize(750, 600)
        self._build_ui()

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── File selector row ──
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        open_btn = QPushButton("Open ABR File…")
        open_btn.clicked.connect(self._open_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(open_btn)
        root.addLayout(file_row)

        # ── Splitter: list | preview ──
        splitter = QSplitter(Qt.Horizontal)

        # Left — brush list
        list_box = QGroupBox("Brushes")
        list_lay = QVBoxLayout(list_box)
        self.brush_list = QListWidget()
        self.brush_list.setIconSize(QSize(48, 48))
        self.brush_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.brush_list.currentItemChanged.connect(self._on_selection_changed)
        list_lay.addWidget(self.brush_list)

        sel_row = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_all.clicked.connect(self.brush_list.selectAll)
        sel_none = QPushButton("Select None")
        sel_none.clicked.connect(self.brush_list.clearSelection)
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        list_lay.addLayout(sel_row)

        splitter.addWidget(list_box)

        # Right — preview + info
        preview_box = QGroupBox("Preview")
        preview_lay = QVBoxLayout(preview_box)
        self.preview = BrushPreviewWidget()
        preview_lay.addWidget(self.preview)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        preview_lay.addWidget(self.info_label)

        splitter.addWidget(preview_box)
        splitter.setSizes([340, 400])
        root.addWidget(splitter, 1)

        # ── Options ──
        opts_box = QGroupBox("Import Options")
        opts_lay = QVBoxLayout(opts_box)

        # Status label
        status_lbl = QLabel(
            "Brushes are saved directly to Krita's resource folder — "
            "no manual file handling needed."
        )
        status_lbl.setWordWrap(True)
        opts_lay.addWidget(status_lbl)

        # Mode selection — Best match vs Advanced
        self.best_match_radio = QRadioButton("Best match (recommended)")
        self.best_match_radio.setChecked(True)
        self.best_match_radio.setToolTip(
            "Saves a .kpp Krita Preset for brushes that carry dynamics "
            "(spacing, scatter, jitter…), or a plain .gbr brush tip otherwise."
        )
        self.advanced_radio = QRadioButton("Advanced (choose formats)")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.best_match_radio)
        self._mode_group.addButton(self.advanced_radio)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.best_match_radio)
        mode_row.addWidget(self.advanced_radio)
        mode_row.addStretch()
        opts_lay.addLayout(mode_row)

        # Advanced format options (hidden while Best match is selected)
        self._adv_widget = QWidget()
        adv_lay = QVBoxLayout(self._adv_widget)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        fmt_row = QHBoxLayout()
        self.gbr_check = QCheckBox("Save as .gbr (GIMP Brush tip)")
        self.gbr_check.setChecked(True)
        self.png_check = QCheckBox("Also save as .png")
        fmt_row.addWidget(self.gbr_check)
        fmt_row.addWidget(self.png_check)
        adv_lay.addLayout(fmt_row)
        self.kpp_check = QCheckBox("Also save as .kpp (Krita Preset — preserves dynamics)")
        adv_lay.addWidget(self.kpp_check)
        self._adv_widget.setVisible(False)
        opts_lay.addWidget(self._adv_widget)

        self.best_match_radio.toggled.connect(
            lambda checked: self._adv_widget.setVisible(not checked)
        )

        self.patterns_check = QCheckBox("Export embedded patterns as PNG")
        self.patterns_check.setVisible(False)
        opts_lay.addWidget(self.patterns_check)

        self.invert_check = QCheckBox(
            "Invert brush images (use if brushes appear inverted)"
        )
        opts_lay.addWidget(self.invert_check)

        self.pressure_check = QCheckBox(
            "Enable pressure sensitivity for size (recommended for tablet use)"
        )
        self.pressure_check.setChecked(True)
        opts_lay.addWidget(self.pressure_check)

        # Paint engine mode — colorsmudge for wet/mixing behaviour
        engine_row = QHBoxLayout()
        engine_label = QLabel("Paint engine:")
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Pixel brush (standard)", "pixel")
        self.engine_combo.addItem("Pencil / Graphite (fine texture)", "pencil")
        self.engine_combo.addItem("Colored pencil (light texture)", "colored_pencil")
        self.engine_combo.addItem("Chalk / Pastel (textured grain)", "chalk")
        self.engine_combo.addItem("Conté / Sanguine (dense grain)", "conte")
        self.engine_combo.addItem("Charcoal (heavy grain)", "charcoal")
        self.engine_combo.addItem("Ink (sharp, solid strokes)", "ink")
        self.engine_combo.addItem("Marker (flat, darken strokes)", "marker")
        self.engine_combo.addItem("Airbrush (soft spray)", "airbrush_soft")
        self.engine_combo.addItem("Spray paint (scattered spray)", "spray")
        self.engine_combo.addItem("Gouache / Oil (paint mixing)", "smudge")
        self.engine_combo.addItem("Oil heavy (palette knife)", "oil_thick")
        self.engine_combo.addItem("Acrylic (opaque, less mixing)", "acrylic")
        self.engine_combo.addItem("Tempera (fast-drying, matte)", "tempera")
        self.engine_combo.addItem("Watercolour (translucent washes)", "wash")
        self.engine_combo.addItem("Encaustic (hot wax, thick)", "encaustic")
        self.engine_combo.addItem("Fresco (wet plaster)", "fresco")
        engine_row.addWidget(engine_label)
        engine_row.addWidget(self.engine_combo)
        engine_row.addStretch()
        opts_lay.addLayout(engine_row)

        root.addWidget(opts_box)

        # ── Auto Import ──
        self._build_auto_import_ui(root)

        # ── Progress ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.import_btn = QPushButton("Import Selected")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._do_import)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.import_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ---------- Auto Import UI construction ----------

    def _build_auto_import_ui(self, root: QVBoxLayout) -> None:
        """Add the Automatic Import settings group to *root*."""
        from . import ABR_BRUSHES_FOLDER
        magic_folder = os.path.join(
            self.resource_dir, ABR_BRUSHES_FOLDER
        )

        auto_box = QGroupBox("Automatic Import")
        auto_lay = QVBoxLayout(auto_box)

        # Magic-folder hint
        hint = QLabel(
            f"<b>Drop folder:</b> Place <code>.abr</code> files in "
            f"<code>{magic_folder}</code> — they are imported automatically "
            f"every time Krita starts."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        auto_lay.addWidget(hint)

        # Enable continuous watcher
        self.auto_enable_check = QCheckBox(
            "Enable continuous watcher (import new files without restarting Krita)"
        )
        auto_lay.addWidget(self.auto_enable_check)

        # Watch folder row
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Watch folder:"))
        self.watch_folder_edit = QLineEdit()
        self.watch_folder_edit.setPlaceholderText(
            f"Leave blank to use the drop folder above ({magic_folder})"
        )
        folder_row.addWidget(self.watch_folder_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_watch_folder)
        folder_row.addWidget(browse_btn)
        auto_lay.addLayout(folder_row)

        # Sub-options row
        sub_row = QHBoxLayout()
        self.recursive_check = QCheckBox("Include sub-folders")
        self.startup_check = QCheckBox("Import on Krita startup")
        self.auto_refresh_check = QCheckBox("Refresh resources after import")
        sub_row.addWidget(self.recursive_check)
        sub_row.addWidget(self.startup_check)
        sub_row.addWidget(self.auto_refresh_check)
        sub_row.addStretch()
        auto_lay.addLayout(sub_row)

        # Status + action row
        status_row = QHBoxLayout()
        self.auto_status_label = QLabel("Status: —")
        self.auto_status_label.setWordWrap(True)
        scan_now_btn = QPushButton("Scan Now")
        scan_now_btn.setToolTip(
            "Immediately scan the watch folder and import any new .abr files"
        )
        scan_now_btn.clicked.connect(self._scan_now)
        status_row.addWidget(self.auto_status_label, 1)
        status_row.addWidget(scan_now_btn)
        auto_lay.addLayout(status_row)

        root.addWidget(auto_box)

        # Populate from saved settings
        self._load_auto_settings()

        # Save settings whenever a control changes
        self.auto_enable_check.toggled.connect(self._save_auto_settings)
        self.watch_folder_edit.editingFinished.connect(self._save_auto_settings)
        self.recursive_check.toggled.connect(self._save_auto_settings)
        self.startup_check.toggled.connect(self._save_auto_settings)
        self.auto_refresh_check.toggled.connect(self._save_auto_settings)

    def _load_auto_settings(self) -> None:
        """Populate auto-import controls from the persisted settings."""
        try:
            s = AutoImportSettings(self.resource_dir)
            self.auto_enable_check.setChecked(s.auto_import_enabled)
            self.watch_folder_edit.setText(s.watch_folder_path)
            self.recursive_check.setChecked(s.watch_recursive)
            self.startup_check.setChecked(s.auto_import_on_startup)
            self.auto_refresh_check.setChecked(s.auto_refresh_resources)
            self._refresh_auto_status()
        except Exception:
            pass

    def _save_auto_settings(self) -> None:
        """Write the current control values to the settings file."""
        try:
            s = AutoImportSettings(self.resource_dir)
            s.auto_import_enabled = self.auto_enable_check.isChecked()
            s.watch_folder_path = self.watch_folder_edit.text().strip()
            s.watch_recursive = self.recursive_check.isChecked()
            s.auto_import_on_startup = self.startup_check.isChecked()
            s.auto_refresh_resources = self.auto_refresh_check.isChecked()
        except Exception:
            pass

    def _refresh_auto_status(self) -> None:
        """Update the status label from the ImportDB."""
        try:
            db = ImportDB(self.resource_dir)
            last_t = db.get_last_import_time()
            if last_t is None:
                self.auto_status_label.setText("Status: no imports recorded yet")
                return
            dt = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(last_t))
            errors = db.get_recent_errors(1)
            if errors:
                last_err = errors[0]
                err_path = os.path.basename(last_err.get("path", ""))
                self.auto_status_label.setText(
                    f"Last import: {dt} | "
                    f"Last error: {err_path}: {last_err.get('message', '')}"
                )
            else:
                self.auto_status_label.setText(f"Last import: {dt}")
        except Exception:
            pass

    def _browse_watch_folder(self) -> None:
        """Open a folder picker to set the watch folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Watch Folder",
            self.watch_folder_edit.text() or self.resource_dir,
        )
        if folder:
            self.watch_folder_edit.setText(folder)
            self._save_auto_settings()

    def _scan_now(self) -> None:
        """Run a one-shot scan of the watch folder immediately."""
        from . import ABR_BRUSHES_FOLDER
        folder = self.watch_folder_edit.text().strip()
        if not folder:
            folder = os.path.join(self.resource_dir, ABR_BRUSHES_FOLDER)

        if not os.path.isdir(folder):
            QMessageBox.warning(
                self, "Folder Not Found",
                f"The watch folder does not exist:\n{folder}\n\n"
                "Please create it and place .abr files inside.",
            )
            return

        self._save_auto_settings()
        s = AutoImportSettings(self.resource_dir)
        options = ImportOptions(auto_refresh=s.auto_refresh_resources)
        db = ImportDB(self.resource_dir)

        result = scan_and_import(
            folder, self.resource_dir,
            recursive=s.watch_recursive,
            db=db, options=options,
        )
        self._refresh_auto_status()

        if result.imported == 0 and result.skipped == 0 and not result.errors:
            QMessageBox.information(
                self, "Scan Complete",
                f"No .abr files found in:\n{folder}",
            )
        elif result.imported == 0 and result.skipped > 0 and not result.errors:
            QMessageBox.information(
                self, "Scan Complete",
                f"All {result.skipped} file(s) are already up-to-date — nothing to import.",
            )
        else:
            msg = (
                f"Imported {result.imported} brush(es) from {folder}.\n"
                f"Skipped (unchanged): {result.skipped}"
            )
            if result.errors:
                msg += f"\n\nErrors ({len(result.errors)}):\n" + "\n".join(result.errors[:10])
            QMessageBox.information(self, "Scan Complete", msg)

    # ---------- Slots ----------

    def _open_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open ABR Brush File", "",
            "Adobe Brush Files (*.abr);;All Files (*)",
        )
        if not filepath:
            return
        self._load_abr_file(filepath)

    def _load_abr_file(self, filepath: str) -> None:
        """Parse an .abr file and populate the brush list."""
        self.file_label.setText(filepath)
        self.brush_list.clear()
        self.brushes = []
        self.patterns = []
        self.preview.setText("Parsing…")

        try:
            parser = ABRParser(filepath=filepath)
            self.brushes = parser.parse()
            self.patterns = parser.patterns
        except Exception as exc:
            QMessageBox.critical(
                self, "Parse Error", f"Failed to parse ABR file:\n{exc}"
            )
            self.preview.setText("Parse failed")
            return

        if not self.brushes:
            QMessageBox.warning(
                self, "No Brushes Found",
                "No brush tips were found in this file.\n"
                "The file may use an unsupported format variant.",
            )
            self.preview.setText("No brushes found")
            return

        for i, tip in enumerate(self.brushes):
            icon = _tip_to_icon(tip)
            label = f"{tip.name or f'Brush {i+1}'}  ({tip.width}×{tip.height})"
            item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, i)
            self.brush_list.addItem(item)

        self.brush_list.selectAll()
        self.import_btn.setEnabled(True)

        if self.brushes:
            self.brush_list.setCurrentRow(0)

        pat_count = len(self.patterns)
        self.patterns_check.setVisible(pat_count > 0)
        if pat_count > 0:
            self.patterns_check.setText(
                f"Export {pat_count} embedded pattern(s) as PNG"
            )
            self.patterns_check.setChecked(True)

        self.file_label.setText(
            f"{filepath} — {len(self.brushes)} brush(es) found"
            + (f", {pat_count} pattern(s)" if pat_count else "")
        )

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            self.preview.setText("Select a brush to preview")
            self.info_label.setText("")
            return

        idx = current.data(Qt.UserRole)
        if idx is None or idx >= len(self.brushes):
            return

        tip = self.brushes[idx]
        self.preview.show_brush(tip)

        ch_label = {1: 'Grayscale', 3: 'RGB', 4: 'RGBA'}.get(tip.channels, f'{tip.channels}ch')
        lines = [
            f"<b>Name:</b> {tip.name}",
            f"<b>Size:</b> {tip.width} × {tip.height} px",
            f"<b>Channels:</b> {ch_label}",
            f"<b>Spacing:</b> {tip.spacing}%",
        ]
        if tip.brush_type == 1:
            lines += [
                f"<b>Angle:</b> {tip.angle}°",
                f"<b>Roundness:</b> {tip.roundness}%",
                f"<b>Hardness:</b> {tip.hardness}%",
            ]
        if tip.dynamics:
            d = tip.dynamics
            dyn_parts = []
            if d.opacity != 100:
                dyn_parts.append(f"Opacity {d.opacity}%")
            if d.flow != 100:
                dyn_parts.append(f"Flow {d.flow}%")
            if d.size_jitter:
                dyn_parts.append(f"Size Jitter {d.size_jitter}%")
            if d.angle_jitter:
                dyn_parts.append(f"Angle Jitter {d.angle_jitter}°")
            if d.roundness_jitter:
                dyn_parts.append(f"Roundness Jitter {d.roundness_jitter}%")
            if d.scatter:
                dyn_parts.append(f"Scatter {d.scatter}%")
            if d.wet_edges:
                dyn_parts.append("Wet Edges")
            if d.noise:
                dyn_parts.append("Noise")
            if d.smoothing:
                dyn_parts.append("Smoothing")
            if dyn_parts:
                lines.append(f"<b>Dynamics:</b> {', '.join(dyn_parts)}")
            # Pressure curves extracted from the ABR
            pressure_parts = []
            if d.size_pressure_curve:
                pressure_parts.append("Size")
            if d.opacity_pressure_curve:
                pressure_parts.append("Opacity")
            if d.flow_pressure_curve:
                pressure_parts.append("Flow")
            if pressure_parts:
                lines.append(
                    f"<b>ABR Pressure Curves:</b> {', '.join(pressure_parts)}"
                )
        self.info_label.setText("<br>".join(lines))

    # ---------- Import logic ----------

    def _do_import(self) -> None:
        selected = self.brush_list.selectedItems()
        if not selected:
            QMessageBox.information(
                self, "Nothing Selected",
                "Please select at least one brush to import.",
            )
            return

        use_best_match = self.best_match_radio.isChecked()

        if not use_best_match:
            save_gbr = self.gbr_check.isChecked()
            save_png = self.png_check.isChecked()
            save_kpp = self.kpp_check.isChecked()
            if not save_gbr and not save_png and not save_kpp:
                QMessageBox.warning(
                    self, "No Format",
                    "Please select at least one output format (.gbr, .png, or .kpp).",
                )
                return
        else:
            save_gbr = save_png = save_kpp = False  # determined per-tip below

        brushes_dir = brushes_dest(self.resource_dir)
        presets_dir = paintoppresets_dest(self.resource_dir)

        invert = self.invert_check.isChecked()
        use_pressure = self.pressure_check.isChecked()
        paint_mode = self.engine_combo.currentData()
        if paint_mode == "pixel":
            paint_mode = None

        self.progress.setVisible(True)
        self.progress.setRange(0, len(selected))
        self.progress.setValue(0)

        imported = 0
        errors: list = []
        written_brush_files: list = []
        written_preset_files: list = []
        written_pattern_files: list = []

        abr_path = self.file_label.text()

        for i, item in enumerate(selected):
            idx = item.data(Qt.UserRole)
            tip = self.brushes[idx]

            safe_name = _friendly_name(tip.name, idx, abr_path)
            pixels = tip.image_data
            ch = tip.channels
            if invert and ch == 1:
                pixels = bytes(255 - b for b in pixels)

            try:
                # Always write a .kpp preset to paintoppresets/
                kpp_path = _unique(os.path.join(presets_dir, f"{safe_name}.kpp"))
                write_kpp(kpp_path, tip, invert=invert, use_pressure=use_pressure,
                          preset_name=safe_name, paint_mode=paint_mode)
                written_preset_files.append(kpp_path)

                # Also write brush tip (.gbr) to brushes/
                if use_best_match:
                    from .abr_parser import ABRParser as _AP
                    gbr_pixels = _AP.get_grayscale(tip) if ch > 1 else pixels
                    if invert and ch > 1:
                        gbr_pixels = bytes(255 - b for b in gbr_pixels)
                    path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                    write_gbr(path, safe_name,
                              tip.width, tip.height, gbr_pixels, tip.spacing,
                              channels=1)
                    written_brush_files.append(path)
                else:
                    if save_gbr:
                        from .abr_parser import ABRParser as _AP
                        gbr_pixels = _AP.get_grayscale(tip) if ch > 1 else pixels
                        if invert and ch > 1:
                            gbr_pixels = bytes(255 - b for b in gbr_pixels)
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                        write_gbr(path, safe_name,
                                  tip.width, tip.height, gbr_pixels, tip.spacing,
                                  channels=1)
                        written_brush_files.append(path)
                    if save_png:
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.png"))
                        write_png(path, tip.width, tip.height, pixels,
                                  channels=ch)
                        written_brush_files.append(path)
                    if save_kpp:
                        pass  # .kpp already written to presets_dir above
                imported += 1
            except Exception as exc:
                errors.append(f"{tip.name}: {exc}")

            self.progress.setValue(i + 1)

        # Export patterns if requested
        pat_errors: list = []
        if self.patterns_check.isChecked() and self.patterns:
            pats_dir = patterns_dest(self.resource_dir)
            for pat in self.patterns:
                try:
                    safe = _sanitize(pat.name or "pattern")
                    path = _unique(os.path.join(pats_dir, f"{safe}.png"))
                    write_png(path, pat.width, pat.height,
                              pat.image_data, channels=pat.channels)
                    written_pattern_files.append(path)
                except Exception as exc:
                    pat_errors.append(f"{pat.name}: {exc}")

        self.progress.setVisible(False)

        # Register presets in Krita's resource database
        if written_preset_files:
            try:
                register_resources(self.resource_dir, written_preset_files, "paintoppresets")
            except Exception:
                pass

        # Generate .bundle file so Krita picks up brushes reliably
        bundle_path = ""
        if imported > 0 and (written_brush_files or written_preset_files):
            try:
                abr_name = self.file_label.text()
                bundle_stem = _sanitize(
                    os.path.splitext(os.path.basename(abr_name))[0]
                ) or "ABR_Import"
                bundle_path = _unique(
                    os.path.join(self.resource_dir, f"{bundle_stem}.bundle")
                )
                write_bundle(
                    bundle_path,
                    written_brush_files,
                    preset_files=written_preset_files or None,
                    pattern_files=written_pattern_files or None,
                    name=bundle_stem,
                    description=f"Imported from {os.path.basename(abr_name)}",
                )
            except Exception:
                bundle_path = ""

        # Replicate written files to all other Krita resource directories
        if imported > 0 and self.extra_resource_dirs:
            import shutil
            src_brushes = brushes_dir
            src_presets = presets_dir
            for extra_dir in self.extra_resource_dirs:
                if extra_dir == self.resource_dir:
                    continue
                for src_dir, dest_fn in [
                    (src_brushes, brushes_dest),
                    (src_presets, paintoppresets_dest),
                ]:
                    if not os.path.isdir(src_dir):
                        continue
                    dst_dir = dest_fn(extra_dir)
                    for fname in os.listdir(src_dir):
                        src_f = os.path.join(src_dir, fname)
                        dst_f = os.path.join(dst_dir, fname)
                        if os.path.isfile(src_f) and not os.path.exists(dst_f):
                            try:
                                shutil.copy2(src_f, dst_f)
                            except OSError:
                                pass
                # Copy .bundle file too
                if bundle_path and os.path.isfile(bundle_path):
                    dst_bundle = os.path.join(
                        extra_dir, os.path.basename(bundle_path)
                    )
                    if not os.path.exists(dst_bundle):
                        try:
                            shutil.copy2(bundle_path, dst_bundle)
                        except OSError:
                            pass
                # Register replicated presets in extra dir's resource DB
                try:
                    extra_presets = [
                        os.path.join(paintoppresets_dest(extra_dir), os.path.basename(p))
                        for p in written_preset_files
                    ]
                    register_resources(extra_dir, extra_presets, "paintoppresets")
                except Exception:
                    pass
            if self.patterns_check.isChecked() and self.patterns:
                src_pats = patterns_dest(self.resource_dir)
                for extra_dir in self.extra_resource_dirs:
                    if extra_dir == self.resource_dir:
                        continue
                    dst_pats = patterns_dest(extra_dir)
                    for fname in os.listdir(src_pats):
                        src_f = os.path.join(src_pats, fname)
                        dst_f = os.path.join(dst_pats, fname)
                        if os.path.isfile(src_f) and not os.path.exists(dst_f):
                            try:
                                shutil.copy2(src_f, dst_f)
                            except OSError:
                                pass

        # Attempt to notify Krita to refresh its resource cache
        try:
            from krita import Krita as _Krita
            _Krita.instance().notifySettingsUpdated()
        except Exception:
            pass

        msg = (
            f"Successfully imported {imported} of {len(selected)} brush(es) "
            f"into Krita's resource folder.\n\n"
            f"Presets: {presets_dir}\n"
            f"Brush tips: {brushes_dir}\n"
        )
        if bundle_path:
            msg += f"Bundle: {os.path.basename(bundle_path)}\n"
        msg += (
            "\nThe new brushes should appear in the Brush Presets "
            "docker after Krita refreshes its resources.\n"
            "If they are not visible yet, go to Settings → Manage Resources "
            "or restart Krita."
        )
        if self.patterns_check.isChecked() and self.patterns:
            exported_pats = len(self.patterns) - len(pat_errors)
            msg += (
                f"\n\nPatterns: exported {exported_pats} of "
                f"{len(self.patterns)} to: "
                f"{patterns_dest(self.resource_dir)}"
            )
        if errors:
            msg += f"\n\nBrush errors ({len(errors)}):\n" + "\n".join(errors[:10])
        if pat_errors:
            msg += f"\n\nPattern errors ({len(pat_errors)}):\n" + "\n".join(pat_errors[:5])

        QMessageBox.information(self, "Import Complete", msg)

