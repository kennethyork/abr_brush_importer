"""
ABR Brush Importer — Krita Python Plugin

Adds a menu entry under Tools → Scripts → Import ABR Brushes…
that opens a dialog to parse, preview, and import Adobe Photoshop .abr
brush files as Krita-compatible brush tips (.gbr).

Out-of-the-box automatic import
--------------------------------
On every Krita startup the plugin scans the ``abr_brushes`` folder
inside Krita's writable resource directory::

    Linux/macOS   ~/.local/share/krita/abr_brushes/
    Windows       %APPDATA%/krita/abr_brushes/

Any ``.abr`` file found there is imported automatically (on a background
thread so the UI is never blocked).  Files that have not changed since
the last import are skipped — so dropping a new brush set in the folder
and restarting Krita is all that is needed.

Additional auto-import options (custom watch folder, continuous watcher,
startup-only mode) can be configured via the importer dialog.
"""

import os
import sys

from krita import Extension, Krita

# Name of the "magic" drop folder inside the Krita resource directory.
ABR_BRUSHES_FOLDER = "abr_brushes"


class ABRBrushImporter(Extension):

    def __init__(self, parent):
        super().__init__(parent)
        self._watcher = None          # FolderWatcherThread (kept alive)
        self._startup_worker = None   # _StartupImportThread (one-shot)

    def setup(self):
        """Called once when the plugin is loaded.

        1. Always scans the ``abr_brushes`` magic folder (if it exists)
           on a background thread so the UI is never blocked.
        2. Reads the persistent auto-import settings and, when configured:
           - Runs a startup scan of the user-defined watch folder.
           - Launches the continuous folder-watcher thread.
        """
        try:
            from .auto_import import AutoImportSettings, FolderWatcherThread
            from .import_db import ImportDB
            from .import_pipeline import ImportOptions

            resource_dir = self._get_resource_dir()
            db = ImportDB(resource_dir)

            # ── 1. Magic "abr_brushes" folder — always on ─────────
            magic_folder = os.path.join(resource_dir, ABR_BRUSHES_FOLDER)
            if os.path.isdir(magic_folder):
                magic_options = ImportOptions(auto_refresh=True)
                self._startup_worker = _StartupImportThread(
                    magic_folder, resource_dir,
                    recursive=False, db=db, options=magic_options,
                )
                self._startup_worker.start()

            # ── 2. User-configured settings ───────────────────────
            settings = AutoImportSettings(resource_dir)
            folder = settings.watch_folder_path

            if not folder or folder == magic_folder:
                # Don't double-scan the same folder.
                pass
            else:
                options = ImportOptions(auto_refresh=settings.auto_refresh_resources)

                if settings.auto_import_on_startup:
                    # Run a one-shot scan if the startup worker isn't already
                    # handling this folder.
                    worker = _StartupImportThread(
                        folder, resource_dir,
                        recursive=settings.watch_recursive,
                        db=db, options=options,
                    )
                    worker.start()
                    # Keep reference so Python doesn't GC it before it finishes.
                    self._startup_worker = worker

            # ── 3. Continuous watcher ─────────────────────────────
            if (
                settings.auto_import_enabled
                and settings.watch_folder_path
                and FolderWatcherThread is not None
            ):
                options = ImportOptions(auto_refresh=settings.auto_refresh_resources)
                self._watcher = FolderWatcherThread(
                    settings.watch_folder_path, resource_dir,
                    recursive=settings.watch_recursive,
                    db=db, options=options,
                )
                self._watcher.start()

        except Exception:
            pass  # Never prevent Krita from starting.

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

        # Restart the watcher if settings changed inside the dialog.
        self._restart_watcher()

        # Ask Krita to reload resources so newly imported brushes/presets
        # appear without requiring a full restart.
        try:
            Krita.instance().notifySettingsUpdated()
        except Exception:
            pass

    def _restart_watcher(self) -> None:
        """Stop any running watcher and start a new one with current settings."""
        try:
            from .auto_import import AutoImportSettings, FolderWatcherThread
            from .import_db import ImportDB
            from .import_pipeline import ImportOptions

            if self._watcher is not None:
                self._watcher.stop()
                self._watcher.wait(2000)
                self._watcher = None

            resource_dir = self._get_resource_dir()
            settings = AutoImportSettings(resource_dir)

            if (
                settings.auto_import_enabled
                and settings.watch_folder_path
                and FolderWatcherThread is not None
            ):
                db = ImportDB(resource_dir)
                options = ImportOptions(auto_refresh=settings.auto_refresh_resources)
                self._watcher = FolderWatcherThread(
                    settings.watch_folder_path, resource_dir,
                    recursive=settings.watch_recursive,
                    db=db, options=options,
                )
                self._watcher.start()
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


# ------------------------------------------------------------------ #
#  Startup import helper thread                                        #
# ------------------------------------------------------------------ #

try:
    from PyQt5.QtCore import QThread

    class _StartupImportThread(QThread):
        """Runs a one-shot folder scan on a background thread at startup."""

        def __init__(self, watch_folder, resource_dir, *,
                     recursive=False, db=None, options=None, parent=None):
            super().__init__(parent)
            self._watch_folder = watch_folder
            self._resource_dir = resource_dir
            self._recursive = recursive
            self._db = db
            self._options = options

        def run(self):
            try:
                from .auto_import import scan_and_import
                scan_and_import(
                    self._watch_folder, self._resource_dir,
                    recursive=self._recursive,
                    db=self._db, options=self._options,
                )
            except Exception:
                pass

except ImportError:
    _StartupImportThread = None  # type: ignore[assignment,misc]


# Register the extension with Krita
Krita.instance().addExtension(ABRBrushImporter(Krita.instance()))
