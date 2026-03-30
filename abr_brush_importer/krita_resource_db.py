"""
Register imported resources in Krita 5's ``resourcecache.sqlite`` database.

Krita 5 tracks all resources (brush tips, presets, patterns, …) in a
SQLite DB.  Simply placing files in the resource directory is not enough
for presets (``paintoppresets/``) — they must also be registered in the
DB so Krita's Brush Presets docker can find them.

This module provides a single function :func:`register_resources` that
inserts entries for any resource files not yet known to the database.

**No PyQt5 / Krita dependencies.**
"""

import hashlib
import os
import sqlite3
import time
from typing import List, Optional

# Krita resource-type IDs (as defined in its resourcecache schema)
_RESOURCE_TYPES = {
    "brushes": 1,
    "paintoppresets": 5,
    "patterns": 7,
}

# The default folder-storage ID used by Krita for its writable directory.
_FOLDER_STORAGE_ID = 1


def register_resources(
    resource_dir: str,
    file_paths: List[str],
    resource_type: str = "paintoppresets",
) -> int:
    """Register resource files in Krita's ``resourcecache.sqlite``.

    Only files that are **not** already registered (by filename) are
    inserted.  Existing entries are left untouched.

    Args:
        resource_dir: The Krita resource root
                      (e.g. ``~/.var/app/org.kde.krita/data/krita/``).
        file_paths:   Absolute paths to ``.kpp`` / ``.gbr`` / … files.
        resource_type: One of ``"paintoppresets"``, ``"brushes"``,
                       ``"patterns"``.

    Returns:
        The number of newly registered resources.
    """
    db_path = os.path.join(resource_dir, "resourcecache.sqlite")
    if not os.path.isfile(db_path):
        return 0

    type_id = _RESOURCE_TYPES.get(resource_type)
    if type_id is None:
        return 0

    if not file_paths:
        return 0

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        # Collect already-registered filenames for this type
        registered = set()
        for row in conn.execute(
            "SELECT filename FROM resources WHERE resource_type_id = ?",
            (type_id,),
        ):
            registered.add(row[0])

        now_ts = int(time.time())
        inserted = 0

        for fpath in file_paths:
            fname = os.path.basename(fpath)
            if fname in registered:
                continue
            if not os.path.isfile(fpath):
                continue

            # Derive a human-readable name from the filename
            name = os.path.splitext(fname)[0]
            # Strip leading underscore added by _sanitize for UUID names
            if name.startswith("_"):
                name = "$" + name[1:]

            md5 = _file_md5(fpath)

            # Insert into resources
            cur = conn.execute(
                "INSERT INTO resources "
                "(resource_type_id, storage_id, name, filename, tooltip,"
                " status, temporary, md5sum) "
                "VALUES (?, ?, ?, ?, ?, 1, 0, ?)",
                (type_id, _FOLDER_STORAGE_ID, name, fname, name, md5),
            )
            resource_id = cur.lastrowid

            # Insert into versioned_resources
            conn.execute(
                "INSERT INTO versioned_resources "
                "(resource_id, storage_id, version, filename, md5sum, timestamp) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (resource_id, _FOLDER_STORAGE_ID, fname, md5, now_ts),
            )
            inserted += 1
            registered.add(fname)

        if inserted:
            conn.commit()
        return inserted
    except Exception:
        return 0
    finally:
        conn.close()


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
