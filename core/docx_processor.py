"""
TOKENFORGE — DOCX Processor
===========================
Extracts headings, paragraphs, bullet points, numbered lists, tables,
and embedded images from Word documents (.docx) using python-docx.

Produces structured, token-optimized Markdown suitable for LLM consumption.
"""

import os
import re
import time
import hashlib
from pathlib import Path

try:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE
except ImportError:
    docx = None

from config import (
    OptimizationMode,
    HASH_ALGORITHM,
    MAX_IMAGE_DIMENSION,
)
from core.token_counter import TokenCounter
from utils.text_utils import (
    render_table,
    normalize_whitespace,
    collapse_blank_lines,
    strip_excessive_newlines,
    compact_table_format,
)
from utils.duplicate_detector import DuplicateTracker


class DOCXProcessor:
    """Process Microsoft Word (.docx) documents into structured Markdown."""

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Initialize the DOCX processor.

        Args:
            optimization_mode: One of 'preservation', 'balanced', 'max_compression'.
        """
        self.optimization_mode = optimization_mode
        self.token_counter = TokenCounter()

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, filepath: str, output_dir: str, assets_dir: str = None) -> dict:
        """
        Main entry point — extract content, format as Markdown, optimize tokens.

        Args:
            filepath:   Path to the input .docx file.
            output_dir: Directory for the generated Markdown.
            assets_dir: Directory for extracted images.

        Returns:
            Result dict with extracted content, token counts, and metadata.
        """
        start_time = time.time()
        warnings: list[str] = []

        if docx is None:
            raise ImportError(
                "python-docx is required for Word document processing. "
                "Install it with: pip install python-docx"
            )

        filepath = str(filepath)
        output_dir = str(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        if assets_dir is None:
            assets_dir = os.path.join(output_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        base_name = Path(filepath).stem
        doc_assets_dir = os.path.join(assets_dir, base_name)
        os.makedirs(doc_assets_dir, exist_ok=True)

        # ── Open the document ─────────────────────────────────────────────────
        try:
            doc = docx.Document(filepath)
        except Exception as exc:
            raise RuntimeError(f"Cannot open Word document '{filepath}': {exc}") from exc

        # ── Extract images ────────────────────────────────────────────────────
        dup_tracker = DuplicateTracker()
        extracted_images = self._extract_images(doc, doc_assets_dir, dup_tracker, warnings)

        # ── Extract paragraphs and structure ──────────────────────────────────
        self._body = self._extract_body(doc)
        paragraphs_data = [b for b in self._body if b["type"] == "p"]

        # ── Extract tables ────────────────────────────────────────────────────
        tables_data = [b["rows"] for b in self._body if b["type"] == "t"]

        # ── Build raw & structured content ────────────────────────────────────
        original_text = self._build_raw_text(paragraphs_data, tables_data)
        structured_markdown = self._build_markdown(
            doc, paragraphs_data, tables_data, extracted_images, base_name
        )

        # ── Optimization based on mode ────────────────────────────────────────
        optimized_text = self._apply_optimization(structured_markdown, self.optimization_mode)

        # ── Token counting ────────────────────────────────────────────────────
        original_tokens = self.token_counter.count(original_text)
        optimized_tokens = self.token_counter.count(optimized_text)
        tokens_saved = original_tokens - optimized_tokens
        reduction_pct = (
            round((tokens_saved / original_tokens) * 100, 2)
            if original_tokens > 0
            else 0.0
        )

        # ── Write output file ─────────────────────────────────────────────────
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
            "images_extracted": [img["path"] for img in extracted_images],
            "tables_found": len(tables_data),
            "pages": max(1, len(paragraphs_data) // 20),  # Word has no explicit pages
            "processing_time": processing_time,
            "warnings": warnings,
            "metadata": {
                "paragraph_count": len(paragraphs_data),
                "headings_detected": sum(1 for p in paragraphs_data if p.get("is_heading")),
                "table_count": len(tables_data),
                "image_count": len(extracted_images),
                "optimization_mode": self.optimization_mode,
            },
        }

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _extract_body(self, doc) -> list[dict]:
        """Walk the document body in true reading order (paragraphs AND tables)."""
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        items: list[dict] = []
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = self._para_dict(Paragraph(child, doc))
                if para:
                    items.append(para)
            elif tag == "tbl":
                tbl = Table(child, doc)
                grid = []
                for row in tbl.rows:
                    cells, last = [], None
                    for cell in row.cells:
                        if cell._tc is last:  # merged cell repeats — keep once
                            continue
                        last = cell._tc
                        cells.append(cell.text.strip().replace("\n", " "))
                    grid.append(cells)
                if grid:
                    items.append({"type": "t", "rows": grid})
        return items

    def _para_dict(self, p):
        text = p.text.strip()
        if not text:
            return None
        style_name = p.style.name if p.style else ""
        heading_level = self._style_to_heading_level(style_name)
        is_list = (
            "List" in style_name
            or text.startswith(("- ", "* ", "• "))
            or bool(re.match(r"^\d+[\.\)]\s", text))
        )
        return {
            "type": "p", "text": text, "style": style_name,
            "heading_level": heading_level, "is_heading": heading_level is not None,
            "is_list": is_list and heading_level is None,
        }

    def _extract_paragraphs(self, doc) -> list[dict]:
        """Extract paragraph text and formatting attributes."""
        paragraphs = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

            style_name = p.style.name if p.style else ""
            heading_level = self._style_to_heading_level(style_name)
            is_list = (
                "List" in style_name
                or "Bullet" in style_name
                or text.startswith(("- ", "* ", "• "))
                or bool(re.match(r"^\d+[\.\)]\s", text))
            )

            paragraphs.append({
                "text": text,
                "style": style_name,
                "heading_level": heading_level,
                "is_heading": heading_level is not None,
                "is_list": is_list,
            })
        return paragraphs

    def _style_to_heading_level(self, style_name: str) -> int | None:
        """Map Word paragraph styles to Markdown heading levels (1-6)."""
        if not style_name:
            return None

        style_lower = style_name.lower()
        if "subtitle" in style_lower:
            return 2
        if style_lower.strip() == "title":
            return 1

        match = re.search(r"heading\s*(\d)", style_lower)
        if match:
            level = int(match.group(1))
            return max(1, min(6, level))

        return None

    def _extract_tables(self, doc) -> list[list[list[str]]]:
        """Extract table grid structures from the document."""
        tables = []
        for table in doc.tables:
            grid = []
            for row in table.rows:
                row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                grid.append(row_cells)
            if grid:
                tables.append(grid)
        return tables

    def _extract_images(
        self,
        doc,
        assets_dir: str,
        dup_tracker: DuplicateTracker,
        warnings: list[str],
    ) -> list[dict]:
        """Extract embedded images from Word document parts with SHA-256 deduplication."""
        extracted = []
        img_counter = 0

        try:
            for rel in doc.part.rels.values():
                if "image" in rel.target_ref:
                    img_part = rel.target_part
                    img_bytes = img_part.blob

                    if not img_bytes or len(img_bytes) < 100:
                        continue

                    # Hash for deduplication
                    hasher = hashlib.new(HASH_ALGORITHM)
                    hasher.update(img_bytes)
                    img_hash = hasher.hexdigest()

                    img_counter += 1
                    ext = Path(rel.target_ref).suffix or ".png"
                    filename = f"image_{img_counter:02d}{ext}"
                    filepath = os.path.join(assets_dir, filename)

                    is_new = dup_tracker.add(img_hash, filepath)
                    if not is_new:
                        orig = dup_tracker.get_original_source(img_hash)
                        extracted.append({
                            "path": orig,
                            "hash": img_hash,
                            "duplicate": True,
                        })
                        continue

                    # Save new image
                    try:
                        with open(filepath, "wb") as f:
                            f.write(img_bytes)
                        rel_path = f"assets/{Path(assets_dir).name}/{filename}"
                        extracted.append({
                            "path": rel_path,
                            "full_path": filepath,
                            "hash": img_hash,
                            "duplicate": False,
                        })
                    except Exception as exc:
                        warnings.append(f"Failed to save image {filename}: {exc}")
        except Exception as exc:
            warnings.append(f"Error accessing document image parts: {exc}")

        return extracted

    # ── Markdown Assembly ─────────────────────────────────────────────────────

    def _build_raw_text(self, paragraphs: list[dict], tables: list[list[list[str]]]) -> str:
        """Construct raw unformatted text for original token counting."""
        body = getattr(self, "_body", None)
        if body:
            lines = []
            for it in body:
                if it["type"] == "t":
                    lines += ["\t".join(r) for r in it["rows"]]
                else:
                    lines.append(it["text"])
            return "\n".join(lines)
        lines = [p["text"] for p in paragraphs]
        for tbl in tables:
            for row in tbl:
                lines.append("\t".join(row))
        return "\n".join(lines)

    def _build_markdown(
        self,
        doc,
        paragraphs: list[dict],
        tables: list[list[list[str]]],
        images: list[dict],
        base_name: str,
    ) -> str:
        """Assemble structured, LLM-ready Markdown from extracted sections."""
        md_lines: list[str] = []
        compact = self.optimization_mode != OptimizationMode.PRESERVATION
        numbered = 0

        for item in getattr(self, "_body", None) or [dict(p, type="p") for p in paragraphs]:
            if item["type"] == "t":
                md_lines.append("")
                md_lines.append(render_table(item["rows"], compact=compact))
                md_lines.append("")
                continue
            text = item["text"]
            if item["is_heading"]:
                md_lines.append(f"\n{'#' * item['heading_level']} {text}\n")
            elif item["is_list"]:
                md_lines.append(f"- {re.sub(r'^[-*•]\s+', '', text)}")
            else:
                md_lines.append(f"\n{text}\n")

        # Images / Visual Assets Reference Section
        unique_images = [img for img in images if not img.get("duplicate")]
        if unique_images:
            md_lines.append("")
            for idx, img in enumerate(unique_images, 1):
                p_rel = img["path"]
                md_lines.append(f"![Figure {idx}]({p_rel})\n")

        content = "\n".join(md_lines)
        return collapse_blank_lines(content)

    def _apply_optimization(self, text: str, mode: str) -> str:
        """Apply token optimization based on selected mode."""
        if mode == OptimizationMode.PRESERVATION:
            return collapse_blank_lines(text)

        elif mode == OptimizationMode.BALANCED:
            text = collapse_blank_lines(text)
            text = strip_excessive_newlines(text)
            # Remove duplicated trailing punctuation or empty markdown artifacts
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        elif mode == OptimizationMode.MAX_COMPRESSION:
            text = collapse_blank_lines(text)
            # Compact markdown lists
            lines = text.split("\n")
            compacted = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("- "):
                    compacted.append(stripped)
                elif stripped:
                    compacted.append(stripped)
            return "\n".join(compacted)

        return text

