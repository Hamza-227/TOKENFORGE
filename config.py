"""
TOKENFORGE Configuration
========================
Central configuration for the TOKENFORGE application.
All settings are local — no cloud, no accounts, no telemetry.
"""

from pathlib import Path

# ── Application ──────────────────────────────────────────────────────────────
APP_NAME = "TOKENFORGE"
APP_VERSION = "1.2.0"
APP_TAGLINE = "Convert documents into token-efficient, LLM-ready content."

# ── Supported formats ────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".docx", ".xlsx", ".csv", ".txt",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif"}
SPREADSHEET_EXTENSIONS = {".xlsx", ".csv"}

# ── Output folder names ──────────────────────────────────────────────────────
OUTPUT_ROOT = "TOKENFORGE_OUTPUT"
OPTIMIZED_DIR = "optimized"
ASSETS_DIR = "assets"
REPORTS_DIR = "reports"
ORIGINALS_DIR = "originals"
SUMMARY_FILE = "TOKENFORGE_SUMMARY.md"

# ── Optimization modes ───────────────────────────────────────────────────────
class OptimizationMode:
    PRESERVATION = "preservation"   # Mode A
    BALANCED = "balanced"           # Mode B
    MAX_COMPRESSION = "max_compression"  # Mode C

    LABELS = {
        "preservation": "A — Preservation First",
        "balanced": "B — Balanced",
        "max_compression": "C — Maximum Compression",
    }

    DESCRIPTIONS = {
        "preservation": (
            "Preserve all extracted information and original assets. "
            "Only formatting is optimized."
        ),
        "balanced": (
            "Remove verified redundancy and use compact representations "
            "while retaining original source references."
        ),
        "max_compression": (
            "Aggressive compact notation and semantic restructuring. "
            "Possible information loss is clearly reported."
        ),
    }

# ── Token counting ───────────────────────────────────────────────────────────
DEFAULT_ENCODING = "cl100k_base"   # GPT-4 / ChatGPT tokenizer

# ── Processing limits ────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 500
MAX_IMAGE_DIMENSION = 4096         # resize images larger than this (px)
OCR_DPI = 300
CHUNK_SIZE = 1024 * 1024           # 1 MB read chunks for large files

# ── Duplicate detection ──────────────────────────────────────────────────────
HASH_ALGORITHM = "sha256"

# ── OCR ──────────────────────────────────────────────────────────────────────
TESSERACT_LANG = "eng"
OCR_CONFIDENCE_THRESHOLD = 40      # minimum confidence (0-100) to keep text

# ── Privacy ──────────────────────────────────────────────────────────────────
TELEMETRY_ENABLED = False           # must remain False
EXTERNAL_API_ENABLED = False        # optional AI features — off by default

