#!/usr/bin/env python3
"""Install the ABR Brush Importer plugin into Krita's pykrita directory.

Usage (after pip install):
    abr-install-krita          # auto-detect Krita location
    abr-install-krita --list   # show detected Krita installs
"""

import os
import shutil
import sys


# All known Krita pykrita locations per platform
def _candidates():
    if sys.platform == "linux":
        home = os.path.expanduser("~")
        return [
            ("Flatpak", os.path.join(home, ".var/app/org.kde.krita/data/krita")),
            ("Snap", os.path.join(home, "snap/krita/current/.local/share/krita")),
            ("Native", os.path.join(home, ".local/share/krita")),
        ]
    elif sys.platform == "darwin":
        return [
            ("macOS", os.path.expanduser("~/Library/Application Support/Krita")),
        ]
    elif sys.platform == "win32":
        return [
            ("Windows", os.path.join(os.environ.get("APPDATA", ""), "krita")),
        ]
    return [
        ("Default", os.path.expanduser("~/.local/share/krita")),
    ]


def _find_package_dir():
    """Return the directory containing the abr_brush_importer package source."""
    # When installed via pip, the package is importable
    import abr_brush_importer
    return os.path.dirname(os.path.abspath(abr_brush_importer.__file__))


def _find_desktop_file():
    """Return the path to abr_brush_importer.desktop, or None."""
    pkg_dir = _find_package_dir()
    # Check next to the package (repo layout)
    parent = os.path.dirname(pkg_dir)
    candidate = os.path.join(parent, "abr_brush_importer.desktop")
    if os.path.isfile(candidate):
        return candidate
    # Check inside the package (pip-installed with package_data)
    candidate = os.path.join(pkg_dir, "abr_brush_importer.desktop")
    if os.path.isfile(candidate):
        return candidate
    return None


def install(target_krita_dir):
    """Copy plugin files into target_krita_dir/pykrita/."""
    pykrita = os.path.join(target_krita_dir, "pykrita")
    dest = os.path.join(pykrita, "abr_brush_importer")
    os.makedirs(dest, exist_ok=True)

    # Also create the drop folder
    abr_folder = os.path.join(target_krita_dir, "abr_brushes")
    os.makedirs(abr_folder, exist_ok=True)

    # Copy all .py files from the installed package
    src_dir = _find_package_dir()
    count = 0
    for fname in os.listdir(src_dir):
        if fname.endswith(".py"):
            shutil.copy2(os.path.join(src_dir, fname), os.path.join(dest, fname))
            count += 1

    # Copy .desktop file
    desktop = _find_desktop_file()
    if desktop:
        shutil.copy2(desktop, os.path.join(pykrita, "abr_brush_importer.desktop"))

    return count


def main():
    if "--list" in sys.argv:
        print("Detected Krita installations:")
        for label, path in _candidates():
            exists = os.path.isdir(path)
            print(f"  {'[x]' if exists else '[ ]'} {label}: {path}")
        return

    # Find all existing Krita dirs
    targets = [(label, path) for label, path in _candidates() if os.path.isdir(path)]

    if not targets:
        print("No Krita installation detected.")
        print("Run with --list to see search locations.")
        print("You can create the directory manually and re-run.")
        sys.exit(1)

    for label, path in targets:
        count = install(path)
        print(f"Installed {count} files to {label}: {path}/pykrita/abr_brush_importer/")

    print()
    print("Next steps:")
    print("  1. Open Krita")
    print("  2. Settings -> Configure Krita -> Python Plugin Manager")
    print("  3. Enable 'ABR Brush Importer'")
    print("  4. Restart Krita")


if __name__ == "__main__":
    main()
