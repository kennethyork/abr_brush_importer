"""
Generate a Krita resource bundle (.bundle) from imported brush/pattern files.

A .bundle is a ZIP archive with the MIME type
``application/x-krita-resourcebundle`` containing:

- ``mimetype``           (uncompressed, first entry)
- ``meta.xml``           (bundle metadata)
- ``META-INF/manifest.xml`` (file listing with MD5 checksums)
- ``brushes/...``        (brush tip files: .gbr, .png, …)
- ``paintoppresets/...``  (full preset files: .kpp)
- ``patterns/...``       (pattern files, optional)

This module has **no PyQt5 / Krita dependencies**.
"""

import hashlib
import os
import time
import zipfile
from typing import List, Optional


_MIMETYPE = "application/x-krita-resourcebundle"


def write_bundle(
    bundle_path: str,
    brush_files: List[str],
    preset_files: Optional[List[str]] = None,
    pattern_files: Optional[List[str]] = None,
    *,
    name: str = "ABR Import",
    author: str = "ABR Brush Importer",
    description: str = "",
) -> str:
    """Create a ``.bundle`` file from a list of brush (and pattern) paths.

    Args:
        bundle_path:   Destination ``.bundle`` file path.
        brush_files:   Absolute paths to brush tip files (.gbr/.png).
        preset_files:  Absolute paths to preset files (.kpp, optional).
        pattern_files: Absolute paths to pattern files (optional).
        name:          Human-readable bundle name shown in Krita.
        author:        Author string for meta.xml.
        description:   Description for meta.xml.

    Returns:
        The path that was written (same as *bundle_path*).
    """
    if preset_files is None:
        preset_files = []
    if pattern_files is None:
        pattern_files = []

    date_str = time.strftime("%d/%m/%Y")

    manifest_entries: list = []
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first entry and stored uncompressed
        zf.writestr("mimetype", _MIMETYPE, compress_type=zipfile.ZIP_STORED)

        # Add brush files
        for fpath in brush_files:
            fname = os.path.basename(fpath)
            arc_name = f"brushes/{fname}"
            data = _read_bytes(fpath)
            if data is None:
                continue
            zf.writestr(arc_name, data)
            md5 = hashlib.md5(data).hexdigest()
            manifest_entries.append(("brushes", arc_name, md5))

        # Add preset files (.kpp → paintoppresets/)
        for fpath in preset_files:
            fname = os.path.basename(fpath)
            arc_name = f"paintoppresets/{fname}"
            data = _read_bytes(fpath)
            if data is None:
                continue
            zf.writestr(arc_name, data)
            md5 = hashlib.md5(data).hexdigest()
            manifest_entries.append(("paintoppresets", arc_name, md5))

        # Add pattern files
        for fpath in pattern_files:
            fname = os.path.basename(fpath)
            arc_name = f"patterns/{fname}"
            data = _read_bytes(fpath)
            if data is None:
                continue
            zf.writestr(arc_name, data)
            md5 = hashlib.md5(data).hexdigest()
            manifest_entries.append(("patterns", arc_name, md5))

        # meta.xml
        zf.writestr("meta.xml", _build_meta_xml(
            name=name, author=author, description=description,
            date_str=date_str,
        ))

        # META-INF/manifest.xml
        zf.writestr("META-INF/manifest.xml",
                     _build_manifest_xml(manifest_entries))

    return bundle_path


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_meta_xml(
    *, name: str, author: str, description: str, date_str: str,
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<meta:meta>\n"
        " <meta:generator>ABR Brush Importer Plugin</meta:generator>\n"
        " <meta:bundle-version>1</meta:bundle-version>\n"
        f" <dc:author>{_xml_escape(author)}</dc:author>\n"
        f" <dc:description>{_xml_escape(description)}</dc:description>\n"
        f" <meta:initial-creator>{_xml_escape(author)}</meta:initial-creator>\n"
        f" <dc:creator>{_xml_escape(author)}</dc:creator>\n"
        f" <meta:creation-date>{date_str}</meta:creation-date>\n"
        f" <meta:dc-date>{date_str}</meta:dc-date>\n"
        f' <meta:meta-userdefined meta:name="email" meta:value=""/>\n'
        f' <meta:meta-userdefined meta:name="license" meta:value="Unknown"/>\n'
        f' <meta:meta-userdefined meta:name="website" meta:value=""/>\n'
        "</meta:meta>\n"
    )


def _build_manifest_xml(entries: list) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<manifest:manifest xmlns:manifest='
        '"urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">',
        ' <manifest:file-entry manifest:media-type='
        '"application/x-krita-resourcebundle" manifest:full-path="/"/>',
    ]
    for media_type, full_path, md5 in entries:
        lines.append(
            f' <manifest:file-entry manifest:media-type="{media_type}"'
            f' manifest:full-path="{_xml_escape(full_path)}"'
            f' manifest:md5sum="{md5}"/>'
        )
    lines.append("</manifest:manifest>\n")
    return "\n".join(lines)
