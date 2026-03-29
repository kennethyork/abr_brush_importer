"""
Core import pipeline for the ABR Brush Importer plugin.

Provides a single, reusable import function ``import_abr_files()`` that
is used by both the interactive dialog and the automatic watcher so
that all import logic lives in one place.

This module has **no PyQt5 / Krita dependencies** so it can be
exercised in a plain Python test environment.  The optional Krita
resource-refresh call is attempted at the end but silently ignored when
Krita is not available.
"""

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

from .abr_parser import ABRParser
from .gbr_writer import write_gbr, write_png
from .kpp_writer import write_kpp
from .utils import _sanitize, _unique, _choose_format, brushes_dest, patterns_dest


# ------------------------------------------------------------------ #
#  Options / Result dataclasses                                        #
# ------------------------------------------------------------------ #

@dataclass
class ImportOptions:
    """Controls how brushes are written during an import run.

    Attributes:
        use_best_match:   If ``True`` (the default), choose ``.kpp`` for
                          brushes with dynamics and ``.gbr`` otherwise.
                          The *save_gbr/png/kpp* flags are only used when
                          this is ``False``.
        save_gbr:         Save ``.gbr`` brush tips (advanced mode).
        save_png:         Also save ``.png`` copies (advanced mode).
        save_kpp:         Also save ``.kpp`` presets (advanced mode).
        invert:           Invert grayscale brush images before writing.
        use_pressure:     Enable size-pressure sensitivity in ``.kpp`` files.
        export_patterns:  Write embedded ABR patterns as ``.png`` files.
        auto_refresh:     Call ``Krita.notifySettingsUpdated()`` after a
                          successful import so new brushes appear without
                          restarting Krita.
    """

    use_best_match: bool = True
    save_gbr: bool = True
    save_png: bool = False
    save_kpp: bool = False
    invert: bool = False
    use_pressure: bool = True
    export_patterns: bool = True
    auto_refresh: bool = True


@dataclass
class ImportResult:
    """Summary returned by :func:`import_abr_files`.

    Attributes:
        imported:        Number of brush tips successfully written.
        skipped:         Number of .abr files skipped because they are
                         unchanged (only relevant when a DB is provided).
        errors:          Per-brush error messages.
        pattern_errors:  Per-pattern error messages.
    """

    imported: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    pattern_errors: List[str] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return len(self.errors) + len(self.pattern_errors)

    @property
    def ok(self) -> bool:
        """``True`` when at least one brush was imported with no errors."""
        return self.imported > 0 and not self.errors


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

def import_abr_files(
    paths,
    resource_dir: str,
    options: Optional[ImportOptions] = None,
    db=None,
    extra_resource_dirs: Optional[List[str]] = None,
) -> ImportResult:
    """Parse and import all ``.abr`` files listed in *paths*.

    Args:
        paths:        Iterable of absolute ``.abr`` file paths.
        resource_dir: Krita writable resource directory.  Brushes are
                      written to ``<resource_dir>/brushes/`` and patterns
                      to ``<resource_dir>/patterns/``.
        options:      :class:`ImportOptions` instance.  Defaults are used
                      when ``None`` is passed.
        db:           Optional :class:`~import_db.ImportDB` instance.
                      When provided, files that have not changed since
                      the last import are skipped and the DB is updated
                      after each file is processed.
        extra_resource_dirs: Additional Krita resource directories to
                      replicate written brush/pattern files into.

    Returns:
        :class:`ImportResult` with counts and per-brush error messages.
    """
    if options is None:
        options = ImportOptions()

    result = ImportResult()
    brushes_dir = brushes_dest(resource_dir)

    for abr_path in paths:
        # ── Skip unchanged files when a DB is available ─────────────
        if db is not None and not db.is_changed(abr_path):
            result.skipped += 1
            continue

        # ── Parse ─────────────────────────────────────────────────
        try:
            parser = ABRParser(filepath=abr_path)
            brushes = parser.parse()
            patterns = parser.patterns
        except Exception as exc:
            msg = f"{os.path.basename(abr_path)}: parse error: {exc}"
            result.errors.append(msg)
            if db is not None:
                db.mark_imported(abr_path, error=str(exc))
                db.log_error(abr_path, str(exc))
            continue

        file_errors: List[str] = []
        imported_count = 0

        # ── Write brushes ─────────────────────────────────────────
        for idx, tip in enumerate(brushes):
            safe_name = _sanitize(tip.name or f"brush_{idx}")
            ch = tip.channels
            pixels = tip.image_data
            if options.invert and ch == 1:
                pixels = bytes(255 - b for b in pixels)

            try:
                if options.use_best_match:
                    fmt = _choose_format(tip)
                    if fmt == "kpp":
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.kpp"))
                        write_kpp(
                            path, tip,
                            invert=options.invert,
                            use_pressure=options.use_pressure,
                        )
                    else:
                        gbr_pixels = ABRParser.get_grayscale(tip) if ch > 1 else pixels
                        if options.invert and ch > 1:
                            gbr_pixels = bytes(255 - b for b in gbr_pixels)
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                        write_gbr(
                            path, tip.name or safe_name,
                            tip.width, tip.height, gbr_pixels, tip.spacing,
                            channels=1,
                        )
                else:
                    if options.save_gbr:
                        gbr_pixels = ABRParser.get_grayscale(tip) if ch > 1 else pixels
                        if options.invert and ch > 1:
                            gbr_pixels = bytes(255 - b for b in gbr_pixels)
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.gbr"))
                        write_gbr(
                            path, tip.name or safe_name,
                            tip.width, tip.height, gbr_pixels, tip.spacing,
                            channels=1,
                        )
                    if options.save_png:
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.png"))
                        write_png(path, tip.width, tip.height, pixels, channels=ch)
                    if options.save_kpp:
                        path = _unique(os.path.join(brushes_dir, f"{safe_name}.kpp"))
                        write_kpp(
                            path, tip,
                            invert=options.invert,
                            use_pressure=options.use_pressure,
                        )
                imported_count += 1
            except Exception as exc:
                file_errors.append(f"{tip.name or safe_name}: {exc}")

        # ── Write patterns ────────────────────────────────────────
        if options.export_patterns and patterns:
            pats_dir = patterns_dest(resource_dir)
            for pat in patterns:
                try:
                    safe = _sanitize(pat.name or "pattern")
                    path = _unique(os.path.join(pats_dir, f"{safe}.png"))
                    write_png(path, pat.width, pat.height,
                              pat.image_data, channels=pat.channels)
                except Exception as exc:
                    result.pattern_errors.append(f"{pat.name}: {exc}")

        result.imported += imported_count
        result.errors.extend(file_errors)

        # ── Update tracking DB ────────────────────────────────────
        if db is not None:
            error_summary = "; ".join(file_errors) if file_errors else None
            db.mark_imported(abr_path, error=error_summary)

    # ── Replicate to extra resource directories ─────────────────
    if extra_resource_dirs and result.imported > 0:
        src_brushes = brushes_dest(resource_dir)
        src_patterns = patterns_dest(resource_dir)
        for extra_dir in extra_resource_dirs:
            if extra_dir == resource_dir:
                continue
            for src_dir, dest_fn in [
                (src_brushes, brushes_dest),
                (src_patterns, patterns_dest),
            ]:
                if not os.path.isdir(src_dir):
                    continue
                dst_dir = dest_fn(extra_dir)
                for fname in os.listdir(src_dir):
                    src_file = os.path.join(src_dir, fname)
                    dst_file = os.path.join(dst_dir, fname)
                    if os.path.isfile(src_file) and not os.path.exists(dst_file):
                        try:
                            shutil.copy2(src_file, dst_file)
                        except OSError:
                            pass

    # ── Refresh Krita resources ───────────────────────────────────
    if options.auto_refresh and result.imported > 0:
        try:
            from krita import Krita as _Krita
            _Krita.instance().notifySettingsUpdated()
        except Exception:
            pass

    return result
