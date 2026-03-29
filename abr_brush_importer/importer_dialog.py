"""
Qt dialog for importing ABR brush files into Krita.

Provides:
  - File browser to select .abr files
  - Thumbnail list with brush names and dimensions
  - Large preview pane with metadata
  - Options: Best-match (recommended) or advanced format selection
  - Batch import directly into Krita's resource folder — no manual
    file handling needed
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QCheckBox,
    QProgressBar, QGroupBox, QMessageBox, QSplitter,
    QAbstractItemView, QRadioButton, QButtonGroup, QWidget,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon

from .abr_parser import ABRParser, BrushTip, BrushPattern
from .gbr_writer import write_gbr, write_png
from .kpp_writer import write_kpp
from .utils import _sanitize, _unique, _choose_format, brushes_dest, patterns_dest


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

    def __init__(self, resource_dir: str, parent=None):
        super().__init__(parent)
        self.resource_dir = resource_dir
        self.brushes: list = []
        self.patterns: list = []

        self.setWindowTitle("ABR Brush Importer")
        self.setMinimumSize(750, 550)
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
        root.addWidget(opts_box)

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

    # ---------- Slots ----------

    def _open_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open ABR Brush File", "",
            "Adobe Brush Files (*.abr);;All Files (*)",
        )
        if not filepath:
            return

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

        invert = self.invert_check.isChecked()
        use_pressure = self.pressure_check.isChecked()

        self.progress.setVisible(True)
        self.progress.setRange(0, len(selected))
        self.progress.setValue(0)

        imported = 0
        errors: list = []

        for i, item in enumerate(selected):
            idx = item.data(Qt.UserRole)
            tip = self.brushes[idx]

            safe_name = _sanitize(tip.name or f"brush_{idx}")
            pixels = tip.image_data
            ch = tip.channels
            if invert and ch == 1:
                pixels = bytes(255 - b for b in pixels)

            try:
                if use_best_match:
                    fmt = _choose_format(tip)
                    if fmt == "kpp":
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.kpp"))
                        write_kpp(path, tip, invert=invert, use_pressure=use_pressure)
                    else:
                        from .abr_parser import ABRParser as _AP
                        gbr_pixels = _AP.get_grayscale(tip) if ch > 1 else pixels
                        if invert and ch > 1:
                            gbr_pixels = bytes(255 - b for b in gbr_pixels)
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                        write_gbr(path, tip.name or safe_name,
                                  tip.width, tip.height, gbr_pixels, tip.spacing,
                                  channels=1)
                else:
                    if save_gbr:
                        from .abr_parser import ABRParser as _AP
                        gbr_pixels = _AP.get_grayscale(tip) if ch > 1 else pixels
                        if invert and ch > 1:
                            gbr_pixels = bytes(255 - b for b in gbr_pixels)
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                        write_gbr(path, tip.name or safe_name,
                                  tip.width, tip.height, gbr_pixels, tip.spacing,
                                  channels=1)
                    if save_png:
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.png"))
                        write_png(path, tip.width, tip.height, pixels,
                                  channels=ch)
                    if save_kpp:
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.kpp"))
                        write_kpp(path, tip, invert=invert, use_pressure=use_pressure)
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
                except Exception as exc:
                    pat_errors.append(f"{pat.name}: {exc}")

        self.progress.setVisible(False)

        # Attempt to notify Krita to refresh its resource cache
        try:
            from krita import Krita as _Krita
            _Krita.instance().notifySettingsUpdated()
        except Exception:
            pass

        msg = (
            f"Successfully imported {imported} of {len(selected)} brush(es) "
            f"into Krita's resource folder.\n\n"
            f"Location: {brushes_dir}\n\n"
            "The new brushes should appear in the Predefined Brush Tips "
            "tab after Krita refreshes its resources.\n"
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

