"""
TOKENFORGE — Duplicate Detection Utilities
============================================
SHA-256-based hashing for files, raw bytes, and text, plus a
``DuplicateTracker`` class that records first-seen sources and
identifies duplicates.
"""

import hashlib
from pathlib import Path
from typing import Dict, List, Optional

from config import HASH_ALGORITHM, CHUNK_SIZE


# ── Hashing helpers ─────────────────────────────────────────────────────────


def hash_file(filepath: str | Path) -> str:
    """Compute the SHA-256 hash of the file at *filepath*.

    Large files are read in chunks (``CHUNK_SIZE`` from config) to keep
    memory usage bounded.

    Returns
    -------
    str
        The hex-digest of the file contents.

    Raises
    ------
    FileNotFoundError
        If *filepath* does not exist or is not a regular file.
    """
    p = Path(filepath)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p}")

    hasher = hashlib.new(HASH_ALGORITHM)
    try:
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as exc:
        raise OSError(f"Cannot read file {p}: {exc}") from exc

    return hasher.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Compute the SHA-256 hash of raw *data*.

    Returns
    -------
    str
        The hex-digest.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"Expected bytes, got {type(data).__name__}")
    return hashlib.new(HASH_ALGORITHM, data).hexdigest()


def hash_text(text: str) -> str:
    """Compute the SHA-256 hash of *text* (encoded as UTF-8).

    Returns
    -------
    str
        The hex-digest.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")
    return hashlib.new(HASH_ALGORITHM, text.encode("utf-8")).hexdigest()


# ── Duplicate Tracker ────────────────────────────────────────────────────────


class DuplicateTracker:
    """Track content hashes and detect duplicates.

    Each hash is associated with one or more *source* identifiers (typically
    file paths).  The first source registered for a given hash is considered
    the "original"; subsequent sources are duplicates.

    Example
    -------
    >>> tracker = DuplicateTracker()
    >>> tracker.add("abc123", "file_a.pdf")
    True
    >>> tracker.add("abc123", "file_b.pdf")
    False
    >>> tracker.is_duplicate("abc123")
    True
    >>> tracker.get_original_source("abc123")
    'file_a.pdf'
    """

    def __init__(self) -> None:
        # hash -> list of source identifiers (first entry = original)
        self._registry: Dict[str, List[str]] = {}
        self._duplicate_count: int = 0

    # ── Core API ─────────────────────────────────────────────────────────

    def add(self, hash_val: str, source: str) -> bool:
        """Register *source* under *hash_val*.

        Returns ``True`` if this is the **first** (new/unique) item for this
        hash.  Returns ``False`` if it is a duplicate.
        """
        if hash_val in self._registry:
            self._registry[hash_val].append(source)
            self._duplicate_count += 1
            return False
        else:
            self._registry[hash_val] = [source]
            return True

    def is_duplicate(self, hash_val: str) -> bool:
        """Return ``True`` if *hash_val* has been seen more than once."""
        sources = self._registry.get(hash_val)
        if sources is None:
            return False
        return len(sources) > 1

    def get_original_source(self, hash_val: str) -> Optional[str]:
        """Return the source path of the first occurrence for *hash_val*.

        Returns ``None`` if *hash_val* has never been registered.
        """
        sources = self._registry.get(hash_val)
        if sources:
            return sources[0]
        return None

    # ── Reporting ────────────────────────────────────────────────────────

    def get_duplicates(self) -> Dict[str, List[str]]:
        """Return a dict mapping each hash to its list of duplicate sources.

        Only hashes with **more than one** source are included.  The first
        source in each list is the original; the rest are duplicates.
        """
        return {
            h: sources
            for h, sources in self._registry.items()
            if len(sources) > 1
        }

    def get_stats(self) -> dict:
        """Return summary statistics.

        Returns
        -------
        dict
            ``unique_items``   — number of distinct hashes registered.
            ``duplicates_found`` — total number of duplicate registrations.
            ``total_items``    — unique + duplicates.
        """
        unique = len(self._registry)
        return {
            "unique_items": unique,
            "duplicates_found": self._duplicate_count,
            "total_items": unique + self._duplicate_count,
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"DuplicateTracker(unique={stats['unique_items']}, "
            f"duplicates={stats['duplicates_found']})"
        )
