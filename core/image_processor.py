"""
TOKENFORGE — Image Processor
=============================
Processes image files (PNG, JPG, JPEG, TIFF) into token-efficient
Markdown representations.  Extracts text via OCR, classifies the image
type, preserves the original asset, and returns a standard result dict.
"""

import os
import shutil
import time
from pathlib import Path

try:
    from PIL import Image, ImageStat
except ImportError:
    raise ImportError(
        "Pillow is required for image processing. Install with: pip install Pillow"
    )

from core.ocr_engine import OCREngine
from core.token_counter import TokenCounter
from utils.duplicate_detector import DuplicateTracker, hash_file, hash_bytes
from config import (
    MAX_IMAGE_DIMENSION,
    OptimizationMode,
)


class ImageProcessor:
    """Converts image files into LLM-optimized Markdown with OCR extraction."""

    # ── Thresholds for heuristic image classification ────────────────────────
    _HIGH_TEXT_RATIO = 0.30      # OCR text-to-pixel ratio for 'text_document'
    _MED_TEXT_RATIO = 0.10       # Lower bound for 'screenshot'
    _COLOR_VARIANCE_LOW = 30.0   # Below → likely diagram/chart
    _EDGE_VARIANCE_HIGH = 50.0   # Above → likely photo

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Initialise the image processor.

        Args:
            optimization_mode: One of 'preservation', 'balanced', 'max_compression'.
        """
        self.mode = optimization_mode
        self.ocr = OCREngine()
        self.duplicates = DuplicateTracker()
        self.token_counter = TokenCounter()

    # ── Public API ───────────────────────────────────────────────────────────

    def process(self, filepath: str, output_dir: str, assets_dir: str = None) -> dict:
        """
        Process a single image file.

        Args:
            filepath:   Absolute path to the source image.
            output_dir: Directory for the optimized Markdown output.
            assets_dir: Directory for preserved image assets (defaults to
                        ``output_dir / assets``).

        Returns:
            Standard TOKENFORGE result dictionary.
        """
        start = time.time()
        filepath = Path(filepath)
        output_dir = Path(output_dir)
        assets_dir = Path(assets_dir) if assets_dir else output_dir / "assets"
        warnings: list[str] = []

        try:
            image = Image.open(filepath)
        except Exception as exc:
            return self._error_result(filepath, str(exc), time.time() - start)

        # Metadata
        metadata = self._extract_metadata(image, filepath)

        # Duplicate check
        file_hash = hash_file(str(filepath))
        is_dup = self.duplicates.is_duplicate(file_hash)
        if is_dup:
            warnings.append("Duplicate image detected (hash already seen).")

        # Resize for OCR if needed
        working_image = self._resize_if_needed(image)

        # OCR
        if not self.ocr.is_available():
            warnings.append("Tesseract OCR is not installed — image text could not be extracted "
                            "(see README → Installation for Tesseract).")
        try:
            ocr_result = self.ocr.extract_text(working_image)
        except Exception as exc:
            ocr_result = {"text": "", "confidence": 0.0}
            warnings.append(f"OCR failed: {exc}")

        ocr_text = ocr_result.get("text", "").strip()

        # Classification
        classification = self._classify_image(working_image, ocr_result)

        # Save image asset
        asset_rel_path = self.save_image_asset(filepath, str(assets_dir), filepath.stem)
        images_extracted = [asset_rel_path] if asset_rel_path else []

        # Build Markdown
        markdown = self._build_markdown(metadata, ocr_result, classification, asset_rel_path)

        # Write Markdown to output_dir
        md_filename = filepath.stem + ".md"
        md_path = output_dir / md_filename
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(markdown, encoding="utf-8")
        except Exception as exc:
            warnings.append(f"Failed to write output: {exc}")

        # Token counts
        original_tokens = self.token_counter.count(ocr_text) if ocr_text else 0
        optimized_tokens = self.token_counter.count(markdown)
        tokens_saved = max(original_tokens - optimized_tokens, 0)
        reduction_pct = round(
            (tokens_saved / original_tokens * 100) if original_tokens > 0 else 0.0, 2
        )

        elapsed = time.time() - start

        return {
            "source_file": str(filepath),
            "output_file": str(md_path),
            "format_type": "markdown",
            "original_text": ocr_text,
            "optimized_text": markdown,
            "original_tokens": original_tokens,
            "optimized_tokens": optimized_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
            "images_extracted": images_extracted,
            "tables_found": 0,
            "pages": 1,
            "processing_time": round(elapsed, 3),
            "warnings": warnings,
            "metadata": metadata,
        }

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _classify_image(self, image: "Image.Image", ocr_result: dict) -> str:
        """
        Heuristically classify an image.

        Returns one of: 'screenshot', 'diagram', 'photo', 'chart',
        'text_document'.
        """
        ocr_text = ocr_result.get("text", "")
        confidence = ocr_result.get("confidence", 0.0)

        # Pixels in the image
        total_pixels = max(image.width * image.height, 1)

        # Rough text density: characters per 1000 pixels
        text_density = len(ocr_text) / (total_pixels / 1000.0)

        # Heavy text → text document or screenshot
        if text_density > self._HIGH_TEXT_RATIO and confidence > 50:
            return "text_document"
        if text_density > self._MED_TEXT_RATIO and confidence > 40:
            return "screenshot"

        # Colour variance analysis (convert to RGB if needed)
        try:
            rgb = image.convert("RGB")
            stat = ImageStat.Stat(rgb)
            # Standard deviation of channels
            stddevs = stat.stddev  # list of 3 floats
            avg_stddev = sum(stddevs) / len(stddevs)
        except Exception:
            avg_stddev = 50.0  # default mid-range

        # Unique colour count for small images (fast path)
        unique_colors = None
        if total_pixels <= 500_000:
            try:
                unique_colors = len(set(rgb.getdata()))
            except Exception:
                unique_colors = None

        # Low colour variance + some text → chart
        if avg_stddev < self._COLOR_VARIANCE_LOW and ocr_text:
            return "chart"

        # Low colour variance, very few unique colours → diagram
        if avg_stddev < self._COLOR_VARIANCE_LOW:
            return "diagram"

        # High variance, no/little text → photo
        if avg_stddev >= self._EDGE_VARIANCE_HIGH and text_density < self._MED_TEXT_RATIO:
            return "photo"

        # Moderate variance with text → screenshot as fallback
        if ocr_text:
            return "screenshot"

        return "photo"

    def _extract_metadata(self, image: "Image.Image", filepath: Path) -> dict:
        """Return essential image metadata."""
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            file_size = 0

        return {
            "width": image.width,
            "height": image.height,
            "format": image.format or Path(filepath).suffix.lstrip(".").upper(),
            "color_mode": image.mode,
            "file_size_bytes": file_size,
            "filename": Path(filepath).name,
        }

    def _resize_if_needed(self, image: "Image.Image") -> "Image.Image":
        """
        Return a resized copy if either dimension exceeds MAX_IMAGE_DIMENSION;
        otherwise return the original image unchanged.
        """
        max_dim = MAX_IMAGE_DIMENSION
        if image.width <= max_dim and image.height <= max_dim:
            return image

        # Calculate scale factor preserving aspect ratio
        scale = min(max_dim / image.width, max_dim / image.height)
        new_w = int(image.width * scale)
        new_h = int(image.height * scale)

        try:
            resized = image.resize((new_w, new_h), Image.LANCZOS)
        except AttributeError:
            # Older Pillow versions
            resized = image.resize((new_w, new_h), Image.ANTIALIAS)
        return resized

    def _build_markdown(
        self,
        metadata: dict,
        ocr_result: dict,
        classification: str,
        asset_path: str,
    ) -> str:
        """Build an LLM-friendly Markdown representation of the image.

        Preservation mode keeps full metadata; the other modes emit only what
        an LLM needs (asset link + OCR text) so the output stays lean.
        """
        filename = metadata.get("filename", "image")
        ocr_text = ocr_result.get("text", "").strip()
        confidence = ocr_result.get("confidence", 0.0)
        lines: list[str] = [f"# {filename}", ""]

        if self.mode == OptimizationMode.PRESERVATION:
            lines.append(f"Type: {classification} | {metadata.get('width', '?')}x{metadata.get('height', '?')} px | "
                         f"{metadata.get('format', '?')} | {metadata.get('color_mode', '?')} | "
                         f"{round(metadata.get('file_size_bytes', 0) / 1024, 1)} KB")
            lines.append("")

        if asset_path:
            lines += [f"![{filename}]({asset_path})", ""]

        if ocr_text:
            if self.mode == OptimizationMode.PRESERVATION:
                lines.append(f"Extracted text (OCR confidence {confidence:.0f}%):")
                lines.append(ocr_text)
            elif self.mode == OptimizationMode.MAX_COMPRESSION:
                lines.append(" ".join(ocr_text.split()))
            else:
                lines.append(ocr_text)
        else:
            lines.append("(no text detected)")
        return "\n".join(lines).strip() + "\n"

    def save_image_asset(
        self,
        image_bytes_or_path,
        assets_dir: str,
        name: str,
    ) -> str:
        """
        Save or copy an image into the assets directory.

        Args:
            image_bytes_or_path: Either a file path (str/Path) or raw bytes.
            assets_dir: Target directory for assets.
            name: Base name for the saved file (without extension).

        Returns:
            Relative path from the output root to the saved asset, e.g.
            ``assets/my_image.png``.  Returns empty string on failure.
        """
        assets_path = Path(assets_dir)
        try:
            assets_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ""

        if isinstance(image_bytes_or_path, (str, Path)):
            src = Path(image_bytes_or_path)
            if not src.exists():
                return ""
            dest_name = name + src.suffix
            dest = assets_path / dest_name
            try:
                shutil.copy2(str(src), str(dest))
            except Exception:
                return ""
        elif isinstance(image_bytes_or_path, bytes):
            dest_name = name + ".png"
            dest = assets_path / dest_name
            try:
                dest.write_bytes(image_bytes_or_path)
            except Exception:
                return ""
        else:
            return ""

        # Return a relative reference using the assets folder name
        return f"assets/{dest_name}"

    # ── Error helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _error_result(filepath: Path, error_msg: str, elapsed: float) -> dict:
        """Return a result dict representing a processing failure."""
        return {
            "source_file": str(filepath),
            "output_file": "",
            "format_type": "markdown",
            "original_text": "",
            "optimized_text": "",
            "original_tokens": 0,
            "optimized_tokens": 0,
            "tokens_saved": 0,
            "reduction_pct": 0.0,
            "images_extracted": [],
            "tables_found": 0,
            "pages": 1,
            "processing_time": round(elapsed, 3),
            "warnings": [f"Processing failed: {error_msg}"],
            "metadata": {},
        }
