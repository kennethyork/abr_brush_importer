"""
Automatic import support for the ABR Brush Importer plugin.

Provides:
- ``AutoImportSettings`` — persistent configuration backed by a JSON
  file in the plugin cache directory (no QSettings / PyQt5 required for
  the settings class itself, so it is testable outside Krita).
- ``FolderWatcherThread`` — a ``QThread`` subclass that polls a
  user-configured folder every few seconds and imports any new or
  changed ``.abr`` files using the shared :mod:`import_pipeline`.
- ``scan_and_import`` — convenience function for a one-shot synchronous
  scan (used on startup and in tests).
"""

import json
import os
import time

from .import_db import ImportDB
from .import_pipeline import ImportOptions, ImportResult, import_abr_files

# ------------------------------------------------------------------ #
#  Settings                                                            #
# ------------------------------------------------------------------ #

_SETTINGS_FILENAME = "auto_import_settings.json"

_DEFAULTS: dict = {
    "auto_import_enabled": False,
    "watch_folder_path": "",
    "watch_recursive": False,
    "auto_import_on_startup": False,
    "auto_refresh_resources": True,
    "max_download_bytes": 200 * 1024 * 1024,
    "auto_download_urls": [],
}


def _settings_path(resource_dir: str) -> str:
    cache_dir = os.path.join(resource_dir, "abr_importer_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, _SETTINGS_FILENAME)


class AutoImportSettings:
    """Persistent auto-import configuration stored as a JSON file.

    The file lives at::

        <resource_dir>/abr_importer_cache/auto_import_settings.json

    All attribute accesses fall back to :data:`_DEFAULTS` when the key
    is absent from the file (forwards-compatibility with new settings
    added in later versions).

    This class does **not** depend on PyQt5 so it can be exercised in
    plain-Python test environments.
    """

    def __init__(self, resource_dir: str) -> None:
        self._path = _settings_path(resource_dir)
        self._data: dict = {}
        self._load()

    # ---------------------------------------------------------------- #
    #  Persistence                                                       #
    # ---------------------------------------------------------------- #

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except Exception:
            self._data = {}

    def save(self) -> None:
        """Write current settings to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  Generic get / set                                                 #
    # ---------------------------------------------------------------- #

    def get(self, key: str):
        """Return the value for *key*, falling back to the default."""
        if key in self._data:
            val = self._data[key]
            default = _DEFAULTS.get(key)
            # Coerce type to match the default where possible.
            if isinstance(default, bool) and not isinstance(val, bool):
                val = str(val).lower() in ("true", "1", "yes")
            elif isinstance(default, int) and not isinstance(val, int):
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    val = default
            elif isinstance(default, list) and not isinstance(val, list):
                val = [val] if val else []
            return val
        return _DEFAULTS.get(key)

    def set(self, key: str, value) -> None:
        """Persist *key* → *value* immediately."""
        self._data[key] = value
        self.save()

    # ---------------------------------------------------------------- #
    #  Typed properties (convenience)                                    #
    # ---------------------------------------------------------------- #

    @property
    def auto_import_enabled(self) -> bool:
        return self.get("auto_import_enabled")

    @auto_import_enabled.setter
    def auto_import_enabled(self, value: bool) -> None:
        self.set("auto_import_enabled", bool(value))

    @property
    def watch_folder_path(self) -> str:
        return self.get("watch_folder_path") or ""

    @watch_folder_path.setter
    def watch_folder_path(self, value: str) -> None:
        self.set("watch_folder_path", value)

    @property
    def watch_recursive(self) -> bool:
        return self.get("watch_recursive")

    @watch_recursive.setter
    def watch_recursive(self, value: bool) -> None:
        self.set("watch_recursive", bool(value))

    @property
    def auto_import_on_startup(self) -> bool:
        return self.get("auto_import_on_startup")

    @auto_import_on_startup.setter
    def auto_import_on_startup(self, value: bool) -> None:
        self.set("auto_import_on_startup", bool(value))

    @property
    def auto_refresh_resources(self) -> bool:
        return self.get("auto_refresh_resources")

    @auto_refresh_resources.setter
    def auto_refresh_resources(self, value: bool) -> None:
        self.set("auto_refresh_resources", bool(value))

    @property
    def max_download_bytes(self) -> int:
        return self.get("max_download_bytes")

    @max_download_bytes.setter
    def max_download_bytes(self, value: int) -> None:
        self.set("max_download_bytes", int(value))

    @property
    def auto_download_urls(self) -> list:
        return self.get("auto_download_urls") or []

    @auto_download_urls.setter
    def auto_download_urls(self, value: list) -> None:
        self.set("auto_download_urls", list(value))


# ------------------------------------------------------------------ #
#  One-shot synchronous scan                                           #
# ------------------------------------------------------------------ #

def scan_and_import(
    watch_folder: str,
    resource_dir: str,
    *,
    recursive: bool = False,
    db: ImportDB = None,
    options: ImportOptions = None,
    extra_resource_dirs: list = None,
) -> ImportResult:
    """Scan *watch_folder* for ``.abr`` files and import new/changed ones.

    This is a **synchronous** helper intended for startup imports and
    unit tests.  The :class:`FolderWatcherThread` calls it in a loop.

    Args:
        watch_folder: Directory to scan.
        resource_dir: Krita writable resource directory.
        recursive:    If ``True``, walk sub-directories as well.
        db:           Optional :class:`~import_db.ImportDB` for change
                      tracking; pass ``None`` to always import everything.
        options:      :class:`~import_pipeline.ImportOptions` controlling
                      output format, inversion, etc.

    Returns:
        :class:`~import_pipeline.ImportResult` with counts and errors.
    """
    if not watch_folder or not os.path.isdir(watch_folder):
        return ImportResult()

    abr_paths: list = []
    if recursive:
        for root, _dirs, files in os.walk(watch_folder):
            for fname in files:
                if fname.lower().endswith(".abr"):
                    abr_paths.append(os.path.join(root, fname))
    else:
        try:
            for entry in os.scandir(watch_folder):
                if entry.is_file() and entry.name.lower().endswith(".abr"):
                    abr_paths.append(entry.path)
        except OSError:
            return ImportResult()

    if not abr_paths:
        return ImportResult()

    return import_abr_files(abr_paths, resource_dir, options, db,
                            extra_resource_dirs=extra_resource_dirs)


# ------------------------------------------------------------------ #
#  Background folder watcher (requires PyQt5)                         #
# ------------------------------------------------------------------ #

try:
    from PyQt5.QtCore import QThread, pyqtSignal

    class FolderWatcherThread(QThread):
        """Background thread that polls a folder for new/changed ``.abr`` files.

        Emits :attr:`import_started`, :attr:`import_finished`, and
        :attr:`error_occurred` signals so the UI can stay up-to-date
        without blocking.

        The thread polls at :attr:`POLL_INTERVAL` second intervals
        (default 5 s).  Call :meth:`stop` and :meth:`wait` to shut it
        down cleanly.
        """

        import_started = pyqtSignal(str)      # path being imported
        import_finished = pyqtSignal(object)  # ImportResult
        error_occurred = pyqtSignal(str)      # error message string

        #: Polling interval in seconds.
        POLL_INTERVAL: float = 5.0

        def __init__(
            self,
            watch_folder: str,
            resource_dir: str,
            *,
            recursive: bool = False,
            db: ImportDB = None,
            options: ImportOptions = None,
            extra_resource_dirs: list = None,
            parent=None,
        ) -> None:
            super().__init__(parent)
            self._watch_folder = watch_folder
            self._resource_dir = resource_dir
            self._recursive = recursive
            self._db = db
            self._options = options or ImportOptions()
            self._extra_resource_dirs = extra_resource_dirs
            self._stop_flag = False

        def stop(self) -> None:
            """Request the thread to stop at the next poll cycle."""
            self._stop_flag = True

        def run(self) -> None:  # noqa: D102 — overrides QThread.run
            while not self._stop_flag:
                try:
                    self._scan_once()
                except Exception as exc:
                    self.error_occurred.emit(str(exc))
                # Sleep in small slices so stop_flag is noticed quickly.
                elapsed = 0.0
                while elapsed < self.POLL_INTERVAL and not self._stop_flag:
                    time.sleep(0.5)
                    elapsed += 0.5

        def _scan_once(self) -> None:
            folder = self._watch_folder
            if not folder or not os.path.isdir(folder):
                return

            abr_paths: list = []
            if self._recursive:
                for root, _dirs, files in os.walk(folder):
                    for fname in files:
                        if fname.lower().endswith(".abr"):
                            abr_paths.append(os.path.join(root, fname))
            else:
                try:
                    for entry in os.scandir(folder):
                        if entry.is_file() and entry.name.lower().endswith(".abr"):
                            abr_paths.append(entry.path)
                except OSError:
                    return

            # Only process files that the DB considers changed.
            changed = [
                p for p in abr_paths
                if self._db is None or self._db.is_changed(p)
            ]
            if not changed:
                return

            for path in changed:
                self.import_started.emit(path)

            result = import_abr_files(
                changed, self._resource_dir, self._options, self._db,
                extra_resource_dirs=self._extra_resource_dirs,
            )
            self.import_finished.emit(result)

except ImportError:  # PyQt5 not available (e.g. test environment)
    FolderWatcherThread = None  # type: ignore[assignment,misc]
