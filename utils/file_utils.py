"""
TOKENFORGE — File Utility Functions
====================================
Helpers for file discovery, validation, path sanitization,
and output directory scaffolding.  Uses pathlib throughout.
"""

import re
import shutil
from pathlib import Path
from typing import List

from config import (
    SUPPORTED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    OUTPUT_ROOT,
    OPTIMIZED_DIR,
    ASSETS_DIR,
    REPORTS_DIR,
    ORIGINALS_DIR,
)


# ── Path / Extension helpers ────────────────────────────────────────────────


def get_file_extension(path: str | Path) -> str:
    """Return the lowercase extension of *path* (including the leading dot).

    >>> get_file_extension("Report.PDF")
    '.pdf'
    """
    return Path(path).suffix.lower()


def is_supported_file(path: str | Path) -> bool:
    """Return True if the file's extension is in SUPPORTED_EXTENSIONS."""
    return get_file_extension(path) in SUPPORTED_EXTENSIONS


# ── Size helpers ─────────────────────────────────────────────────────────────


def get_file_size_mb(path: str | Path) -> float:
    """Return the size of the file at *path* in megabytes.

    Raises FileNotFoundError if the file does not exist.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p}")
    return p.stat().st_size / (1024 * 1024)


def is_within_size_limit(path: str | Path) -> bool:
    """Return True if the file is at or below MAX_FILE_SIZE_MB."""
    try:
        return get_file_size_mb(path) <= MAX_FILE_SIZE_MB
    except FileNotFoundError:
        return False


# ── Directory helpers ────────────────────────────────────────────────────────


def ensure_directory(path: str | Path) -> Path:
    """Create *path* (and parents) if it does not already exist.

    Returns the resolved Path object.
    """
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Cannot create directory {p}: {exc}") from exc
    return p.resolve()


# ── Filename sanitization ───────────────────────────────────────────────────


def safe_filename(name: str) -> str:
    """Sanitize *name* for safe filesystem use.

    * Strips leading/trailing whitespace.
    * Replaces spaces and runs of special characters with underscores.
    * Removes characters that are not alphanumeric, underscore, hyphen, or dot.
    * Collapses consecutive underscores.

    >>> safe_filename("  My Report (final version) [2].pdf  ")
    'My_Report_final_version_2_.pdf'
    """
    name = name.strip()
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Remove characters that are not safe for filenames
    name = re.sub(r"[^\w.\-]", "_", name)
    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores (but not from extension)
    stem, dot, ext = name.rpartition(".")
    if dot:
        stem = stem.strip("_")
        return f"{stem}.{ext}" if stem else f"file.{ext}"
    return name.strip("_") or "file"


# ── File collection ─────────────────────────────────────────────────────────


def collect_files_from_folder(folder_path: str | Path) -> List[Path]:
    """Recursively find all supported files under *folder_path*.

    Returns a sorted list of Path objects whose extensions are in
    SUPPORTED_EXTENSIONS.  Hidden directories (starting with '.') are
    skipped.
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    collected: List[Path] = []
    try:
        for item in sorted(root.rglob("*")):
            # Skip hidden files/dirs *inside* the chosen folder (not the folder's own
            # path) and never re-scan our own output folder.
            rel_parts = item.relative_to(root).parts
            if any(part.startswith(".") or part == OUTPUT_ROOT for part in rel_parts):
                continue
            if item.is_file() and is_supported_file(item):
                collected.append(item)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot access some files under {root}: {exc}"
        ) from exc

    return collected


# ── Safe copy ────────────────────────────────────────────────────────────────


def copy_file_safe(src: str | Path, dst: str | Path) -> Path:
    """Copy *src* to *dst* without overwriting an existing file.

    If *dst* already exists, a numeric suffix is appended to the stem
    (e.g. ``report_1.pdf``, ``report_2.pdf``).

    Returns the Path actually written to.
    """
    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.is_file():
        raise FileNotFoundError(f"Source file not found: {src_path}")

    # Ensure the destination directory exists
    ensure_directory(dst_path.parent)

    # Avoid overwriting
    if dst_path.exists():
        stem = dst_path.stem
        suffix = dst_path.suffix
        parent = dst_path.parent
        counter = 1
        while dst_path.exists():
            dst_path = parent / f"{stem}_{counter}{suffix}"
            counter += 1

    try:
        shutil.copy2(str(src_path), str(dst_path))
    except OSError as exc:
        raise OSError(
            f"Failed to copy {src_path} -> {dst_path}: {exc}"
        ) from exc

    return dst_path


# ── Output structure ─────────────────────────────────────────────────────────


def create_output_structure(base_path: str | Path) -> dict:
    """Create the full TOKENFORGE_OUTPUT directory tree under *base_path*.

    Directory layout::

        <base_path>/
          TOKENFORGE_OUTPUT/
            optimized/
            assets/
            reports/
            originals/

    Returns a dict mapping logical names to their resolved Path objects::

        {
            "root":      Path(...TOKENFORGE_OUTPUT),
            "optimized": Path(...TOKENFORGE_OUTPUT/optimized),
            "assets":    Path(...TOKENFORGE_OUTPUT/assets),
            "reports":   Path(...TOKENFORGE_OUTPUT/reports),
            "originals": Path(...TOKENFORGE_OUTPUT/originals),
        }
    """
    base = Path(base_path)
    if base.name == OUTPUT_ROOT:
        root = base
    else:
        root = base / OUTPUT_ROOT

    dirs = {
        "root": root,
        "optimized": root / OPTIMIZED_DIR,
        "assets": root / ASSETS_DIR,
        "reports": root / REPORTS_DIR,
        "originals": root / ORIGINALS_DIR,
    }

    for name, dir_path in dirs.items():
        ensure_directory(dir_path)

    return {k: v.resolve() for k, v in dirs.items()}
