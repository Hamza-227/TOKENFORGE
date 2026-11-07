"""
TOKENFORGE — PDF Processor
===========================
Extracts text, tables, images, and headings from PDF files using PyMuPDF (fitz).
Supports scanned-page OCR, header/footer removal, and optimization modes.

Produces structured Markdown output suitable for LLM consumption.
"""

import os
import re
import time
import hashlib
from pathlib import Path
from collections import Counter

try:
    import pymupdf as fitz  # Modern PyMuPDF
except ImportError:
    try:
        import fitz  # PyMuPDF fallback
    except ImportError:
        fitz = None

from config import (
    OptimizationMode,
    HASH_ALGORITHM,
    MAX_IMAGE_DIMENSION,
    OCR_DPI,
)
from core.token_counter import TokenCounter
from core.ocr_engine import OCREngine
from utils.text_utils import (
    render_table,
    normalize_whitespace,
    collapse_blank_lines,
    strip_excessive_newlines,
)
from utils.duplicate_detector import DuplicateTracker


class PDFProcessor:
    """Process PDF files into structured, token-optimized Markdown."""

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Initialize the PDF processor.

        Args:
            optimization_mode: One of 'preservation', 'balanced', 'max_compression'.
        """
        self.optimization_mode = optimization_mode
        self.token_counter = TokenCounter()
        self.ocr_engine = OCREngine()

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, filepath: str, output_dir: str, assets_dir: str = None) -> dict:
        """
        Main entry point — process a PDF and return a result dict.

        Args:
            filepath:   Path to the input PDF file.
            output_dir: Directory for the generated Markdown.
            assets_dir: Directory for extracted images (created if needed).

        Returns:
            Result dict with extracted content, token counts, and metadata.
        """
        start_time = time.time()
        warnings: list[str] = []

        if fitz is None:
            raise ImportError(
                "PyMuPDF (fitz) is required for PDF processing. "
                "Install it with: pip install PyMuPDF"
            )

        filepath = str(filepath)
        output_dir = str(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        if assets_dir is None:
            assets_dir = os.path.join(output_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        # Duplicate tracker for image deduplication
        dup_tracker = DuplicateTracker()

        # ── Open the PDF ──────────────────────────────────────────────────────
        try:
            doc = fitz.open(filepath)
        except Exception as exc:
            raise RuntimeError(f"Cannot open PDF '{filepath}': {exc}") from exc

        total_pages = len(doc)
        pages_data: list[dict] = []
        all_images: list[dict] = []
        all_tables: list[list[list[str]]] = []
        all_headings: list[dict] = []

        # ── First pass: collect raw text per page for header/footer detection ─
        raw_page_texts: list[str] = []
        for page in doc:
            raw_page_texts.append(self._extract_page_text(page))

        repeated_lines = self._detect_repeated_headers_footers(raw_page_texts)

        # ── Second pass: full extraction per page ─────────────────────────────
        for page_num in range(total_pages):
            page = doc[page_num]
            page_info: dict = {"page_num": page_num + 1, "text": "", "is_scanned": False,
                               "items": [], "tables": [], "headings": [], "images": []}

            if self._is_scanned_page(page):
                page_info["is_scanned"] = True
                try:
                    ocr_text = self._ocr_page(page, page_num, doc)
                except Exception as exc:
                    warnings.append(f"OCR failed on page {page_num + 1}: {exc}")
                    ocr_text = ""
                if not ocr_text and not self.ocr_engine.is_available():
                    warnings.append(
                        f"Page {page_num + 1} is a scan but Tesseract is not installed — no text extracted."
                    )
                page_info["text"] = ocr_text
                page_info["items"] = [("p", 0, para.strip()) for para in re.split(r"\n{2,}", ocr_text) if para.strip()]
            else:
                page_info["text"] = raw_page_texts[page_num]
                try:
                    items, tables, headings = self._page_items(page, repeated_lines)
                    page_info["items"], page_info["tables"], page_info["headings"] = items, tables, headings
                    all_tables.extend(tables)
                    all_headings.extend(headings)
                except Exception as exc:
                    warnings.append(f"Layout analysis failed on page {page_num + 1}: {exc}")
                    page_info["items"] = [("p", 0, self._remove_repeated_lines(page_info["text"], repeated_lines))]

            try:
                images = self._extract_images(page, page_num, doc, assets_dir, dup_tracker)
                all_images.extend(images)
                page_info["images"] = images
            except Exception as exc:
                warnings.append(f"Image extraction failed on page {page_num + 1}: {exc}")

            pages_data.append(page_info)

        doc.close()

        # ── Build Markdown ────────────────────────────────────────────────────
        original_text = "\n\n".join(p["text"] for p in pages_data)
        total_pages = total_pages or 1
        markdown = self._build_markdown(pages_data, all_images, all_tables, all_headings)
        optimized_text = self._apply_optimization(markdown, self.optimization_mode)
        if not optimized_text.strip() and original_text.strip():
            warnings.append("Layout analysis produced no text; fell back to plain extraction.")
            optimized_text = self._apply_optimization(original_text, self.optimization_mode)

        # ── Token counts ──────────────────────────────────────────────────────
        original_tokens = self.token_counter.count(original_text)
        optimized_tokens = self.token_counter.count(optimized_text)
        tokens_saved = original_tokens - optimized_tokens
        reduction_pct = (
            round((tokens_saved / original_tokens) * 100, 2)
            if original_tokens > 0
            else 0.0
        )

        # ── Write output file ────────────────────────────────────────────────
        base_name = Path(filepath).stem
        output_file = os.path.join(output_dir, f"{base_name}.md")
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(optimized_text)
        except Exception as exc:
            warnings.append(f"Failed to write output file: {exc}")

        processing_time = round(time.time() - start_time, 3)

        return {
            "source_file": filepath,
            "output_file": output_file,
            "format_type": "markdown",
            "original_text": original_text,
            "optimized_text": optimized_text,
            "original_tokens": original_tokens,
            "optimized_tokens": optimized_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
            "images_extracted": [img["path"] for img in all_images],
            "tables_found": len(all_tables),
            "pages": total_pages,
            "processing_time": processing_time,
            "warnings": warnings,
            "metadata": {
                "scanned_pages": sum(1 for p in pages_data if p["is_scanned"]),
                "headings_detected": len(all_headings),
                "repeated_headers_removed": len(repeated_lines),
                "optimization_mode": self.optimization_mode,
            },
        }

    # ── In-order page analysis ────────────────────────────────────────────────

    @staticmethod
    def _norm_line(line: str) -> str:
        # Only page-number-like digits are normalised; other digits are content.
        return re.sub(r"(?i)\bpage\s+\d+(?:\s+of\s+\d+)?", "page #", line.strip())

    _PAGE_NO_RE = re.compile(r"^\s*(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|-\s*\d+\s*-|\d+\s*/\s*\d+)\s*$", re.I)

    def _page_items(self, page, repeated_lines):
        """
        Return ``(items, tables, headings)`` for a page in true reading order.
        ``items`` is a list of ``(kind, level, payload)`` with kind in
        {'h', 'p', 't'}; tables are kept at their real position and their cell
        text is NOT repeated as body text.
        """
        # Tables (ignore 1-row / 1-column false positives)
        table_boxes, table_items = [], []
        if hasattr(page, "find_tables"):
            try:
                for t in page.find_tables().tables:
                    rows = [[(c or "").strip() for c in r] for r in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                        table_boxes.append(fitz.Rect(t.bbox))
                        table_items.append((t.bbox[1], ("t", 0, rows)))
            except Exception:
                table_boxes, table_items = [], []

        blocks = page.get_text("dict", sort=True)["blocks"]
        sizes = [round(sp["size"], 1) for b in blocks if b.get("type") == 0
                 for ln in b["lines"] for sp in ln["spans"] if sp["text"].strip()]
        body = Counter(sizes).most_common(1)[0][0] if sizes else 10.0

        items, headings = list(table_items), []
        for b in blocks:
            if b.get("type") != 0:
                continue
            c = fitz.Point((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2)
            if any(box.contains(c) for box in table_boxes):
                continue
            lines, max_size, all_bold = [], 0.0, True
            for ln in b["lines"]:
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                txt = "".join(sp["text"] for sp in spans).strip()
                if self._norm_line(txt) in repeated_lines or self._PAGE_NO_RE.match(txt):
                    continue
                lines.append(txt)
                max_size = max(max_size, max(sp["size"] for sp in spans))
                all_bold = all_bold and all(sp["flags"] & 16 or "bold" in sp["font"].lower() for sp in spans)
            if not lines:
                continue
            text = self._reflow(lines)
            ratio = max_size / body if body else 1.0
            level = 0
            if len(text) <= 120 and len(lines) <= 2:
                if ratio >= 1.6: level = 1
                elif ratio >= 1.3: level = 2
                elif ratio >= 1.12: level = 3
                elif all_bold and len(text) <= 80 and not text.endswith((".", ",", ";")): level = 4
            if level:
                headings.append({"text": text, "level": level})
                items.append((b["bbox"][1], ("h", level, text)))
            else:
                items.append((b["bbox"][1], ("p", 0, text)))

        items.sort(key=lambda x: x[0])
        return [it for _, it in items], [it[2] for _, it in table_items], headings

    @staticmethod
    def _reflow(lines: list[str]) -> str:
        """Join wrapped lines into one paragraph (de-hyphenating where safe)."""
        out = ""
        for ln in lines:
            if not out:
                out = ln
            elif out.endswith("-") and ln[:1].islower() and len(out) > 1 and out[-2].isalpha():
                out = out[:-1] + ln
            else:
                out += " " + ln
        return out

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_page_text(self, page) -> str:
        """
        Extract selectable text from a single PDF page.

        Args:
            page: A fitz.Page object.

        Returns:
            Extracted text as a string.
        """
        try:
            text = page.get_text("text")
            return text.strip() if text else ""
        except Exception:
            return ""

    def _extract_tables(self, page) -> list[list[list[str]]]:
        """
        Extract tables from a PDF page.

        Uses fitz's built-in table finder if available (PyMuPDF ≥ 1.23),
        falling back to heuristic line-based detection.

        Args:
            page: A fitz.Page object.

        Returns:
            List of tables, each table being a list of rows, each row a list of cell strings.
        """
        tables: list[list[list[str]]] = []

        # Try built-in table finder (PyMuPDF ≥ 1.23)
        if hasattr(page, "find_tables"):
            try:
                tab_finder = page.find_tables()
                for table in tab_finder.tables:
                    extracted = table.extract()
                    # Clean up None → empty string
                    cleaned: list[list[str]] = []
                    for row in extracted:
                        cleaned.append([str(cell) if cell is not None else "" for cell in row])
                    if cleaned:
                        tables.append(cleaned)
                return tables
            except Exception:
                pass  # Fall through to heuristic

        # Heuristic: look for tab-separated or pipe-separated blocks in text
        try:
            text = page.get_text("text")
            if not text:
                return tables

            lines = text.split("\n")
            current_table: list[list[str]] = []

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    # End of possible table block
                    if len(current_table) >= 2:
                        tables.append(current_table)
                    current_table = []
                    continue

                # Detect pipe-delimited rows
                if "|" in stripped:
                    cells = [c.strip() for c in stripped.split("|") if c.strip()]
                    if len(cells) >= 2:
                        current_table.append(cells)
                        continue

                # Detect tab-delimited rows
                if "\t" in stripped:
                    cells = [c.strip() for c in stripped.split("\t") if c.strip()]
                    if len(cells) >= 2:
                        current_table.append(cells)
                        continue

                # Detect multiple-space–delimited rows (≥ 3 columns heuristic)
                parts = re.split(r"\s{2,}", stripped)
                if len(parts) >= 3:
                    current_table.append(parts)
                    continue

                # Line doesn't look tabular — flush any partial table
                if len(current_table) >= 2:
                    tables.append(current_table)
                current_table = []

            # Flush last block
            if len(current_table) >= 2:
                tables.append(current_table)

        except Exception:
            pass

        return tables

    def _extract_images(
        self,
        page,
        page_num: int,
        doc,
        assets_dir: str,
        dup_tracker: "DuplicateTracker",
    ) -> list[dict]:
        """
        Extract images from a PDF page, save to assets_dir with deduplication.

        Args:
            page:        A fitz.Page object.
            page_num:    Zero-based page index.
            doc:         The fitz.Document.
            assets_dir:  Directory to save images into.
            dup_tracker: DuplicateTracker for deduplication.

        Returns:
            List of dicts: {path, width, height, hash}.
        """
        images: list[dict] = []

        try:
            image_list = page.get_images(full=True)
        except Exception:
            return images

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                img_ext = base_image.get("ext", "png")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Compute hash for deduplication
                img_hash = hashlib.new(HASH_ALGORITHM, image_bytes).hexdigest()

                if dup_tracker.is_duplicate(img_hash):
                    # Return reference to already-saved copy
                    existing = dup_tracker.get_path(img_hash)
                    if existing:
                        images.append(
                            {
                                "path": existing,
                                "width": width,
                                "height": height,
                                "hash": img_hash,
                            }
                        )
                    continue

                # Save the image
                filename = f"page_{page_num + 1:03d}_img_{img_idx + 1:02d}.{img_ext}"
                img_path = os.path.join(assets_dir, filename)
                with open(img_path, "wb") as f:
                    f.write(image_bytes)

                dup_tracker.register(img_hash, img_path)

                images.append(
                    {
                        "path": img_path,
                        "width": width,
                        "height": height,
                        "hash": img_hash,
                    }
                )
            except Exception:
                continue

        return images

    def _detect_headings(self, page) -> list[dict]:
        """
        Detect headings on a page based on font size and weight.

        Args:
            page: A fitz.Page object.

        Returns:
            List of dicts: {text, level, position}.
        """
        headings: list[dict] = []

        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            return headings

        # Collect all font sizes to determine body-text baseline
        font_sizes: list[float] = []
        for block in blocks:
            if block.get("type") != 0:  # only text blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    if size > 0:
                        font_sizes.append(size)

        if not font_sizes:
            return headings

        # Body-text size is the most common font size
        size_counter = Counter(round(s, 1) for s in font_sizes)
        body_size = size_counter.most_common(1)[0][0]

        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text_parts: list[str] = []
                max_size = 0.0
                is_bold = False

                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue
                    line_text_parts.append(span_text)
                    size = span.get("size", 0)
                    if size > max_size:
                        max_size = size
                    flags = span.get("flags", 0)
                    if flags & 2 ** 4:  # bold flag
                        is_bold = True

                full_text = " ".join(line_text_parts).strip()
                if not full_text:
                    continue

                # Determine heading level based on size ratio to body text
                ratio = max_size / body_size if body_size > 0 else 1.0

                level = 0
                if ratio >= 1.8:
                    level = 1
                elif ratio >= 1.5:
                    level = 2
                elif ratio >= 1.25:
                    level = 3
                elif ratio >= 1.1 and is_bold:
                    level = 4
                elif is_bold and max_size >= body_size:
                    level = 5

                if level > 0:
                    position = block.get("bbox", (0, 0, 0, 0))
                    headings.append(
                        {
                            "text": full_text,
                            "level": level,
                            "position": position,
                        }
                    )

        return headings

    def _is_scanned_page(self, page) -> bool:
        """
        Check if a page is a scanned image (no selectable text but has images).

        Args:
            page: A fitz.Page object.

        Returns:
            True if the page appears to be a scanned/image-only page.
        """
        try:
            text = page.get_text("text").strip()
            images = page.get_images(full=True)

            # Heuristic: very little text (< 20 chars) and at least one image
            has_text = len(text) > 20
            has_images = len(images) > 0

            return (not has_text) and has_images
        except Exception:
            return False

    def _ocr_page(self, page, page_num: int, doc) -> str:
        """
        Perform OCR on a scanned PDF page.

        Renders the page to a pixmap and passes it to the OCR engine.

        Args:
            page:     A fitz.Page object.
            page_num: Zero-based page index.
            doc:      The fitz.Document.

        Returns:
            OCR-extracted text.
        """
        try:
            zoom = OCR_DPI / 72.0  # default PDF DPI is 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            text = self.ocr_engine.ocr_image_bytes(img_bytes)
            return text.strip() if text else ""
        except Exception as exc:
            raise RuntimeError(f"OCR failed for page {page_num + 1}: {exc}") from exc

    def _detect_repeated_headers_footers(
        self, page_texts: list[str], min_occurrences: int = 3
    ) -> set[str]:
        """
        Detect lines that repeat across multiple pages (likely headers/footers).

        Args:
            page_texts:     List of raw text strings, one per page.
            min_occurrences: Minimum number of pages a line must appear on.

        Returns:
            Set of repeated line strings.
        """
        if len(page_texts) < min_occurrences:
            min_occurrences = max(2, len(page_texts))
        elif len(page_texts) > 6:
            min_occurrences = max(min_occurrences, int(len(page_texts) * 0.5))

        line_counter: Counter = Counter()

        for text in page_texts:
            if not text:
                continue
            lines = text.split("\n")
            # Only check first 3 and last 3 lines of each page
            candidate_lines = set()
            for line in lines[:3] + lines[-3:]:
                stripped = line.strip()
                # Skip very short lines and page numbers
                # Never treat lines carrying contact data / links as boilerplate.
                if "@" in stripped or "http" in stripped or "www." in stripped:
                    continue
                if stripped and len(stripped) > 3 and not stripped.isdigit():
                    candidate_lines.add(self._norm_line(stripped))
            for cand in candidate_lines:
                line_counter[cand] += 1

        repeated = {
            line for line, count in line_counter.items() if count >= min_occurrences
        }
        return repeated

    def _remove_repeated_lines(self, text: str, repeated_lines: set[str]) -> str:
        """
        Remove repeated header/footer lines from page text.

        Args:
            text:            The page text.
            repeated_lines:  Set of lines to remove.

        Returns:
            Cleaned text.
        """
        if not repeated_lines or not text:
            return text

        lines = text.split("\n")
        cleaned = [line for line in lines
                   if self._norm_line(line) not in repeated_lines and not self._PAGE_NO_RE.match(line)]
        return "\n".join(cleaned)

    def _build_markdown(
        self,
        pages_data: list[dict],
        images: list[dict],
        tables: list[list[list[str]]],
        headings: list[dict],
    ) -> str:
        """
        Assemble final Markdown from all extracted content.

        Args:
            pages_data: List of per-page extraction dicts.
            images:     All extracted images.
            tables:     All extracted tables.
            headings:   All detected headings.

        Returns:
            Structured Markdown string.
        """
        md_parts: list[str] = []
        mode = self.optimization_mode
        multi = len(pages_data) > 1

        for page_info in pages_data:
            if multi and mode == OptimizationMode.PRESERVATION:
                md_parts.append(f"<!-- Page {page_info['page_num']} -->")
            elif multi and mode == OptimizationMode.BALANCED:
                md_parts.append(f"[p.{page_info['page_num']}]")

            for kind, level, payload in page_info.get("items", []):
                if kind == "h":
                    md_parts.append(f"{'#' * min(level, 6)} {payload}")
                elif kind == "t":
                    md_parts.append(self._table_to_markdown(payload))
                else:
                    md_parts.append(payload)

            for img in page_info.get("images", []):
                img_path = img.get("path", "")
                md_parts.append(f"![{os.path.basename(img_path)}]({img_path})")

        return "\n\n".join(md_parts)

    def _table_to_markdown(self, table: list[list[str]]) -> str:
        """
        Convert a table (list of rows) to a Markdown table string.

        Args:
            table: List of rows, each row a list of cell strings.

        Returns:
            Markdown-formatted table string.
        """
        return render_table(table, compact=self.optimization_mode != OptimizationMode.PRESERVATION)

    def _apply_optimization(self, text: str, mode: str) -> str:
        """
        Apply optimization to the Markdown text based on the selected mode.

        Args:
            text: The raw Markdown text.
            mode: Optimization mode string.

        Returns:
            Optimized text.
        """
        if mode == OptimizationMode.PRESERVATION:
            # Minimal cleanup — preserve everything
            text = collapse_blank_lines(text)
            return text

        if mode == OptimizationMode.BALANCED:
            # Remove redundant whitespace, collapse blank lines
            text = normalize_whitespace(text)
            text = collapse_blank_lines(text)
            text = strip_excessive_newlines(text)
            return text

        if mode == OptimizationMode.MAX_COMPRESSION:
            # Aggressive compression
            text = normalize_whitespace(text)
            text = collapse_blank_lines(text)
            text = strip_excessive_newlines(text)

            # Remove HTML comments (page markers)
            text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

            # Remove horizontal rules
            text = re.sub(r"\n---\n", "\n", text)

            # Collapse multiple blank lines to single
            text = re.sub(r"\n{3,}", "\n\n", text)

            # Remove trailing whitespace on every line
            text = "\n".join(line.rstrip() for line in text.split("\n"))

            return text.strip()

        # Fallback: balanced
        text = normalize_whitespace(text)
        text = collapse_blank_lines(text)
        return text
