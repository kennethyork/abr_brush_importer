"""
ABR Brush Importer — Krita Python Plugin

Adds a menu entry under Tools → Scripts → Import ABR Brushes…
that opens a dialog to parse, preview, and import Adobe Photoshop .abr
brush files as Krita-compatible brush tips (.gbr).
"""

import os
import sys

from krita import Extension, Krita


class ABRBrushImporter(Extension):

    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction(
            "abr_brush_importer",
            "Import ABR Brushes…",
            "tools/scripts",
        )
        action.triggered.connect(self._show_dialog)

    def _show_dialog(self):
        from .importer_dialog import ABRImporterDialog

        resource_dir = self._get_resource_dir()
        parent_window = Krita.instance().activeWindow().qwindow()
        dialog = ABRImporterDialog(resource_dir, parent_window)
        dialog.exec_()

        # Ask Krita to reload resources so newly imported brushes/presets
        # appear without requiring a full restart.
        try:
            Krita.instance().notifySettingsUpdated()
        except Exception:
            pass

    @staticmethod
    def _get_resource_dir() -> str:
        """Return Krita's writable resource directory."""
        if sys.platform == "linux":
            default = os.path.expanduser("~/.local/share/krita")
        elif sys.platform == "darwin":
            default = os.path.expanduser("~/Library/Application Support/Krita")
        elif sys.platform == "win32":
            default = os.path.join(os.environ.get("APPDATA", ""), "krita")
        else:
            default = os.path.expanduser("~/.local/share/krita")

        if os.path.isdir(default):
            return default

        os.makedirs(default, exist_ok=True)
        return default


# Register the extension with Krita
Krita.instance().addExtension(ABRBrushImporter(Krita.instance()))
