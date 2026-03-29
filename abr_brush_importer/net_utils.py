"""
Network utility helpers for the ABR Brush Importer plugin.

Provides:
  - URL-based cache key computation (hash of URL)
  - Download of .abr or .zip files from a URL with size limit
  - Safe extraction of .abr files from zip archives (zip-slip prevention)
  - Cache directory management (get path, list cached files, clear)

All networking uses only the Python standard library (urllib.request).
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
import zipfile
from typing import Optional

# Maximum download size in bytes (default 200 MB)
MAX_DOWNLOAD_BYTES: int = 200 * 1024 * 1024

# Name of the plugin-specific cache folder inside the Krita writable resource dir
CACHE_FOLDER_NAME: str = "abr_importer_cache"

# Download timeout in seconds
DOWNLOAD_TIMEOUT: int = 30


def url_cache_key(url: str) -> str:
    """Return a stable, filesystem-safe cache key derived from a URL.

    The key is the first 16 hex characters of the SHA-256 digest of the
    URL string (UTF-8 encoded).

    >>> url_cache_key("https://example.com/brushes.abr")  # doctest: +ELLIPSIS
    '...'
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return digest[:16]


def get_cache_dir(resource_dir: str) -> str:
    """Return the path to the plugin cache directory (creates it if absent)."""
    cache_dir = os.path.join(resource_dir, CACHE_FOLDER_NAME)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def cached_path(resource_dir: str, url: str, filename: str) -> str:
    """Return the full path where *url* with *filename* would be cached."""
    key = url_cache_key(url)
    _, ext = os.path.splitext(filename)
    return os.path.join(get_cache_dir(resource_dir), f"{key}_{filename}")


def list_cached_files(resource_dir: str) -> list:
    """Return a sorted list of absolute paths to all cached files."""
    cache_dir = get_cache_dir(resource_dir)
    return sorted(
        os.path.join(cache_dir, f)
        for f in os.listdir(cache_dir)
        if os.path.isfile(os.path.join(cache_dir, f))
    )


def clear_cache(resource_dir: str) -> int:
    """Delete all files in the cache directory.

    Returns the number of files deleted.
    """
    cache_dir = get_cache_dir(resource_dir)
    count = 0
    for fname in os.listdir(cache_dir):
        fpath = os.path.join(cache_dir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
            count += 1
    return count


def download_url(
    url: str,
    dest_path: str,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: int = DOWNLOAD_TIMEOUT,
    progress_callback=None,
) -> None:
    """Download *url* to *dest_path*, enforcing a maximum size limit.

    Args:
        url: The URL to download.
        dest_path: Destination file path (parent directory must exist).
        max_bytes: Maximum number of bytes to download.
        timeout: Socket timeout in seconds.
        progress_callback: Optional callable(downloaded_bytes, total_bytes_or_None).
            Called periodically during download. ``total_bytes_or_None`` is the
            Content-Length (int) if the server provided it, otherwise ``None``.

    Raises:
        urllib.error.URLError: On network or HTTP errors.
        ValueError: If the server reports a Content-Length exceeding ``max_bytes``,
            or if the actual downloaded size exceeds ``max_bytes``.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ABRBrushImporter/1.0"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Check Content-Length header first to fail fast
        content_length = resp.headers.get("Content-Length")
        total: Optional[int] = None
        if content_length is not None:
            try:
                total = int(content_length)
            except ValueError:
                total = None
            if total is not None and total > max_bytes:
                raise ValueError(
                    f"Server reports Content-Length {total:,} bytes which exceeds "
                    f"the {max_bytes:,}-byte limit."
                )

        chunk_size = 65536  # 64 KiB
        downloaded = 0

        with open(dest_path, "wb") as fout:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    # Remove incomplete file before raising
                    fout.close()
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    raise ValueError(
                        f"Download exceeded the {max_bytes:,}-byte limit "
                        f"({downloaded:,} bytes received so far)."
                    )
                fout.write(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)


def extract_abr_from_zip(zip_path: str, dest_dir: str) -> list:
    """Extract all .abr files from *zip_path* into *dest_dir*.

    Security:
    - Only members whose names end with ``.abr`` (case-insensitive) are extracted.
    - Each member path is sanitised to prevent zip-slip directory traversal:
      the output path is always a direct child of *dest_dir*.

    Args:
        zip_path: Path to the zip archive.
        dest_dir: Directory into which .abr files are written.

    Returns:
        A sorted list of absolute paths to extracted .abr files.

    Raises:
        zipfile.BadZipFile: If the archive is not a valid zip file.
        ValueError: If the archive contains no .abr members.
    """
    os.makedirs(dest_dir, exist_ok=True)
    extracted = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        abr_members = [
            m for m in zf.namelist() if m.lower().endswith(".abr")
        ]
        if not abr_members:
            raise ValueError("The zip archive contains no .abr files.")

        for member in abr_members:
            # Sanitise: use only the basename, strip any path components
            safe_name = os.path.basename(member)
            if not safe_name:
                continue  # skip entries that are directory names

            out_path = os.path.join(dest_dir, safe_name)
            # Double-check the resolved path is inside dest_dir (zip-slip guard)
            real_dest = os.path.realpath(dest_dir)
            real_out = os.path.realpath(out_path)
            if not real_out.startswith(real_dest + os.sep):
                continue  # silently skip suspicious entries

            data = zf.read(member)
            with open(out_path, "wb") as fout:
                fout.write(data)
            extracted.append(out_path)

    return sorted(extracted)


def fetch_abr(
    url: str,
    resource_dir: str,
    *,
    force_refresh: bool = False,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: int = DOWNLOAD_TIMEOUT,
    progress_callback=None,
) -> list:
    """Download (or retrieve from cache) the ABR file(s) at *url*.

    Handles both direct ``.abr`` URLs and ``.zip`` archives containing
    ``.abr`` files.

    Args:
        url: HTTP/HTTPS URL pointing to a ``.abr`` or ``.zip`` file.
        resource_dir: Krita writable resource directory used as the cache root.
        force_refresh: If ``True``, re-download even if the file is cached.
        max_bytes: Maximum download size in bytes.
        timeout: Socket timeout in seconds.
        progress_callback: Forwarded to :func:`download_url`.

    Returns:
        A list of absolute paths to ``.abr`` files ready for parsing.

    Raises:
        urllib.error.URLError: On network errors.
        ValueError: On oversized downloads or bad zip archives.
    """
    import posixpath
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    raw_filename = posixpath.basename(parsed.path) or "download"
    # Keep original filename for the cache entry
    dest_filename = f"{url_cache_key(url)}_{raw_filename}"
    cache_dir = get_cache_dir(resource_dir)
    dest_path = os.path.join(cache_dir, dest_filename)

    if force_refresh and os.path.exists(dest_path):
        os.remove(dest_path)

    if not os.path.exists(dest_path):
        download_url(
            url,
            dest_path,
            max_bytes=max_bytes,
            timeout=timeout,
            progress_callback=progress_callback,
        )

    # Decide what to do based on the downloaded file type
    lower_name = raw_filename.lower()
    if lower_name.endswith(".zip") or _is_zip(dest_path):
        abr_extract_dir = os.path.join(cache_dir, f"{url_cache_key(url)}_extracted")
        if force_refresh and os.path.isdir(abr_extract_dir):
            import shutil
            shutil.rmtree(abr_extract_dir)
        # Always re-extract if the directory is missing or empty
        if not os.path.isdir(abr_extract_dir) or not os.listdir(abr_extract_dir):
            return extract_abr_from_zip(dest_path, abr_extract_dir)
        return sorted(
            os.path.join(abr_extract_dir, f)
            for f in os.listdir(abr_extract_dir)
            if f.lower().endswith(".abr")
        )
    else:
        # Treat as a direct .abr file
        return [dest_path]


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _is_zip(path: str) -> bool:
    """Return True if *path* looks like a zip archive (magic bytes check)."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except OSError:
        return False
