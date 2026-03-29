"""Utility helpers shared between the dialog, standalone converter, and tests.

These helpers are intentionally free of PyQt5 / Krita dependencies so they
can be exercised in a plain Python test environment.
"""

import os

from .abr_parser import BrushTip


# ------------------------------------------------------------------ #
#  Filename helpers                                                    #
# ------------------------------------------------------------------ #

def _sanitize(name: str) -> str:
    """Return a filesystem-safe filename stem from *name*."""
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name)
    safe = safe.strip().strip(".")
    return safe[:100] if safe else "brush"


def _unique(path: str) -> str:
    """Return *path* or a numbered variant so no existing file is overwritten."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


# ------------------------------------------------------------------ #
#  Format selection                                                    #
# ------------------------------------------------------------------ #

def _choose_format(tip: BrushTip) -> str:
    """Choose the best output format for *tip*.

    Returns ``'kpp'`` when the tip carries dynamics that benefit from a full
    Krita preset, otherwise returns ``'gbr'`` for a plain brush tip.
    """
    return "kpp" if tip.dynamics else "gbr"


# ------------------------------------------------------------------ #
#  Destination path helpers                                            #
# ------------------------------------------------------------------ #

def brushes_dest(resource_dir: str) -> str:
    """Return (and create) the brushes sub-directory under *resource_dir*."""
    path = os.path.join(resource_dir, "brushes")
    os.makedirs(path, exist_ok=True)
    return path


def patterns_dest(resource_dir: str) -> str:
    """Return (and create) the patterns sub-directory under *resource_dir*."""
    path = os.path.join(resource_dir, "patterns")
    os.makedirs(path, exist_ok=True)
    return path


def paintoppresets_dest(resource_dir: str) -> str:
    """Return (and create) the paintoppresets sub-directory under *resource_dir*."""
    path = os.path.join(resource_dir, "paintoppresets")
    os.makedirs(path, exist_ok=True)
    return path
