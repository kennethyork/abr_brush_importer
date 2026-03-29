"""
Import tracking database for the ABR Brush Importer plugin.

Keeps a lightweight JSON record of every .abr file that has been
imported — keyed by absolute path and storing the file's mtime and
the timestamp of the import.  The watcher and pipeline use this to
skip files that have not changed since the last import.

This module has **no PyQt5 / Krita dependencies** so it can be
exercised in a plain Python test environment.
"""

import json
import os
import time

# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

_DB_FILENAME = "abr_import_db.json"
_MAX_ERRORS = 50  # number of recent error entries to retain


def _db_path(resource_dir: str) -> str:
    """Return the absolute path to the JSON tracking file."""
    cache_dir = os.path.join(resource_dir, "abr_importer_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, _DB_FILENAME)


def _empty_db() -> dict:
    return {"files": {}, "errors": []}


# ------------------------------------------------------------------ #
#  ImportDB                                                            #
# ------------------------------------------------------------------ #

class ImportDB:
    """Persistent record of imported .abr files.

    Data is stored as a JSON file inside the plugin cache directory::

        <resource_dir>/abr_importer_cache/abr_import_db.json

    The ``files`` section maps absolute path → {mtime, imported_at, error}.
    The ``errors`` section is a most-recent-first list of error entries
    (path, message, time).

    Usage::

        db = ImportDB(resource_dir)
        if db.is_changed("/path/to/brushes.abr"):
            result = import_abr_files(["/path/to/brushes.abr"], ...)
            db.mark_imported("/path/to/brushes.abr")
    """

    def __init__(self, resource_dir: str) -> None:
        self._path = _db_path(resource_dir)
        self._data = _empty_db()
        self._load()

    # ---------------------------------------------------------------- #
    #  Persistence                                                       #
    # ---------------------------------------------------------------- #

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            self._data["files"] = loaded.get("files", {})
            self._data["errors"] = loaded.get("errors", [])
        except Exception:
            # Corrupt DB — start fresh rather than crash.
            self._data = _empty_db()

    def save(self) -> None:
        """Flush the in-memory state to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except Exception:
            pass  # Non-fatal — we'll try again next time.

    # ---------------------------------------------------------------- #
    #  File tracking                                                     #
    # ---------------------------------------------------------------- #

    def is_changed(self, path: str) -> bool:
        """Return ``True`` if *path* should be (re-)imported.

        A file is considered changed when:
        - It has never been imported before, **or**
        - Its modification time differs from the recorded value.
        """
        record = self._data["files"].get(path)
        if record is None:
            return True
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            return True
        return current_mtime != record.get("mtime")

    def mark_imported(self, path: str, *, error: str = None) -> None:
        """Record that *path* has been processed.

        Args:
            path:  Absolute path to the .abr file.
            error: Optional short error summary if the import failed.
        """
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        self._data["files"][path] = {
            "mtime": mtime,
            "imported_at": time.time(),
            "error": error,
        }
        self.save()

    # ---------------------------------------------------------------- #
    #  Error log                                                         #
    # ---------------------------------------------------------------- #

    def log_error(self, path: str, message: str) -> None:
        """Prepend an error entry and trim the list to *_MAX_ERRORS*."""
        self._data["errors"].insert(0, {
            "path": path,
            "message": message,
            "time": time.time(),
        })
        self._data["errors"] = self._data["errors"][:_MAX_ERRORS]
        self.save()

    def get_recent_errors(self, limit: int = 10) -> list:
        """Return the *limit* most-recent error entries (newest first)."""
        return self._data["errors"][:limit]

    # ---------------------------------------------------------------- #
    #  Query helpers                                                     #
    # ---------------------------------------------------------------- #

    def get_last_import_time(self, path: str = None):
        """Return the most recent ``imported_at`` timestamp (float or None).

        If *path* is given, return the timestamp for that specific file.
        Otherwise return the most recent timestamp across all files.
        """
        if path is not None:
            return self._data["files"].get(path, {}).get("imported_at")
        times = [
            rec["imported_at"]
            for rec in self._data["files"].values()
            if rec.get("imported_at") is not None
        ]
        return max(times) if times else None

    def tracked_paths(self) -> list:
        """Return a list of all tracked file paths."""
        return list(self._data["files"].keys())
