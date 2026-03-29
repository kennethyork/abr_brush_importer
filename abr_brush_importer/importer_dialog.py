"""
Qt dialog for importing ABR brush files into Krita.

Provides:
  - File browser to select .abr files
  - Thumbnail list with brush names and dimensions
  - Large preview pane with metadata
  - Options: output format (.gbr / .png), invert toggle
  - Batch import of selected brushes to Krita's resource folder
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QCheckBox,
    QProgressBar, QGroupBox, QMessageBox, QSplitter,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon

from .abr_parser import ABRParser, BrushTip, BrushPattern
from .gbr_writer import write_gbr, write_png


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
        fmt_row = QHBoxLayout()
        self.gbr_check = QCheckBox("Save as .gbr (GIMP Brush)")
        self.gbr_check.setChecked(True)
        self.png_check = QCheckBox("Also save as .png")
        fmt_row.addWidget(self.gbr_check)
        fmt_row.addWidget(self.png_check)
        opts_lay.addLayout(fmt_row)

        self.invert_check = QCheckBox(
            "Invert brush images (use if brushes appear inverted)"
        )
        opts_lay.addWidget(self.invert_check)
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

        self.file_label.setText(
            f"{filepath} — {len(self.brushes)} brush(es) found"
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

        save_gbr = self.gbr_check.isChecked()
        save_png = self.png_check.isChecked()
        if not save_gbr and not save_png:
            QMessageBox.warning(
                self, "No Format",
                "Please select at least one output format (.gbr or .png).",
            )
            return

        brushes_dir = os.path.join(self.resource_dir, "brushes")
        os.makedirs(brushes_dir, exist_ok=True)

        invert = self.invert_check.isChecked()

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
                if save_gbr:
                    from .abr_parser import ABRParser as _AP
                    # GBR works best with grayscale; convert RGBA/RGB
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
                imported += 1
            except Exception as exc:
                errors.append(f"{tip.name}: {exc}")

            self.progress.setValue(i + 1)

        self.progress.setVisible(False)

        msg = (
            f"Successfully imported {imported} of {len(selected)} brush(es)\n"
            f"to: {brushes_dir}\n\n"
            "Restart Krita or go to Settings → Manage Resources\n"
            "to see the new brush tips in the Predefined tab."
        )
        if errors:
            msg += f"\n\nErrors ({len(errors)}):\n" + "\n".join(errors[:10])

        QMessageBox.information(self, "Import Complete", msg)


# ------------------------------------------------------------------ #
#  Filename helpers                                                    #
# ------------------------------------------------------------------ #

def _sanitize(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:100] if safe else "brush"


def _unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"
