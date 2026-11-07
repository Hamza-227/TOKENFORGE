"""
TOKENFORGE — PPTX Processor
=============================
Extracts slides, text, tables, images, charts, and speaker notes from
PowerPoint (.pptx) files using python-pptx.

Produces structured Markdown output suitable for LLM consumption.
"""

import os
import time
import hashlib
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except ImportError:
    Presentation = None

from config import (
    OptimizationMode,
    HASH_ALGORITHM,
)
from core.token_counter import TokenCounter
from utils.text_utils import (
    render_table,
    normalize_whitespace,
    collapse_blank_lines,
    strip_excessive_newlines,
)
from utils.duplicate_detector import DuplicateTracker


class PPTXProcessor:
    """Process PowerPoint (.pptx) files into structured, token-optimized Markdown."""

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Initialize the PPTX processor.

        Args:
            optimization_mode: One of 'preservation', 'balanced', 'max_compression'.
        """
        self.optimization_mode = optimization_mode
        self.token_counter = TokenCounter()

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, filepath: str, output_dir: str, assets_dir: str = None) -> dict:
        """
        Main entry point — process a PPTX and return a result dict.

        Args:
            filepath:   Path to the input PPTX file.
            output_dir: Directory for the generated Markdown.
            assets_dir: Directory for extracted images (created if needed).

        Returns:
            Result dict with extracted content, token counts, and metadata.
        """
        start_time = time.time()
        warnings: list[str] = []

        if Presentation is None:
            raise ImportError(
                "python-pptx is required for PPTX processing. "
                "Install it with: pip install python-pptx"
            )

        filepath = str(filepath)
        output_dir = str(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        if assets_dir is None:
            assets_dir = os.path.join(output_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        dup_tracker = DuplicateTracker()

        # ── Open the presentation ─────────────────────────────────────────────
        try:
            prs = Presentation(filepath)
        except Exception as exc:
            raise RuntimeError(f"Cannot open PPTX '{filepath}': {exc}") from exc

        # Attempt to get presentation title from slide master or first slide
        pres_title = self._get_presentation_title(prs)

        slides_data: list[dict] = []
        all_images: list[dict] = []
        all_tables_count = 0

        for slide_num, slide in enumerate(prs.slides, start=1):
            try:
                slide_info = self._extract_slide_content(slide, slide_num)
            except Exception as exc:
                warnings.append(f"Failed to extract slide {slide_num}: {exc}")
                slide_info = {
                    "slide_num": slide_num,
                    "title": f"Slide {slide_num}",
                    "text_blocks": [],
                    "bullet_points": [],
                    "tables": [],
                    "notes": "",
                    "images": [],
                    "charts": [],
                }

            # Extract images
            try:
                images = self._extract_images_from_slide(
                    slide, slide_num, assets_dir, dup_tracker
                )
                slide_info["images"] = images
                all_images.extend(images)
            except Exception as exc:
                warnings.append(f"Image extraction failed on slide {slide_num}: {exc}")
                slide_info["images"] = []

            # Extract tables
            try:
                tables = self._extract_tables_from_slide(slide)
                slide_info["tables"] = tables
                all_tables_count += len(tables)
            except Exception as exc:
                warnings.append(f"Table extraction failed on slide {slide_num}: {exc}")
                slide_info["tables"] = []

            # Extract chart data
            try:
                charts = self._extract_chart_data(slide)
                slide_info["charts"] = charts
            except Exception as exc:
                warnings.append(f"Chart extraction failed on slide {slide_num}: {exc}")
                slide_info["charts"] = []

            slides_data.append(slide_info)

        # If no explicit title, infer from first slide

        # ── Build Markdown ────────────────────────────────────────────────────
        original_parts: list[str] = []
        for sd in slides_data:
            original_parts.append(sd.get("title", ""))
            for block in sd.get("text_blocks", []):
                original_parts.append(block)
            for bp in sd.get("bullet_points", []):
                original_parts.append(bp)
            if sd.get("notes"):
                original_parts.append(sd["notes"])
        original_text = "\n\n".join(original_parts)

        markdown = self._build_markdown(slides_data, pres_title)
        optimized_text = self._apply_optimization(markdown, self.optimization_mode)

        # ── Token counts ──────────────────────────────────────────────────────
        original_tokens = self.token_counter.count(original_text)
        optimized_tokens = self.token_counter.count(optimized_text)
        tokens_saved = original_tokens - optimized_tokens
        reduction_pct = (
            round((tokens_saved / original_tokens) * 100, 2)
            if original_tokens > 0
            else 0.0
        )

        # ── Write output file ─────────────────────────────────────────────────
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
            "tables_found": all_tables_count,
            "pages": len(slides_data),
            "processing_time": processing_time,
            "warnings": warnings,
            "metadata": {
                "presentation_title": pres_title,
                "total_slides": len(slides_data),
                "charts_found": sum(len(sd.get("charts", [])) for sd in slides_data),
                "slides_with_notes": sum(
                    1 for sd in slides_data if sd.get("notes")
                ),
                "optimization_mode": self.optimization_mode,
            },
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_presentation_title(self, prs) -> str:
        """
        Attempt to extract the presentation title from core properties.

        Args:
            prs: A Presentation object.

        Returns:
            Title string, or empty string.
        """
        try:
            t = (prs.core_properties.title or "").strip() if prs.core_properties else ""
            if t and t.lower() not in ("powerpoint presentation", "presentation", "untitled"):
                return t
        except Exception:
            pass
        return ""

    def _extract_slide_content(self, slide, slide_num: int) -> dict:
        """
        Extract all content from a single slide.

        Args:
            slide:     A pptx Slide object.
            slide_num: 1-based slide number.

        Returns:
            Dict with title, text_blocks, bullet_points, notes, etc.
        """
        title = ""
        text_blocks: list[str] = []
        bullet_points: list[str] = []
        title_shape = slide.shapes.title

        def walk(shapes):
            # reading order: top-to-bottom, then left-to-right; recurse into groups
            ordered = sorted(shapes, key=lambda sh: (getattr(sh, "top", 0) or 0, getattr(sh, "left", 0) or 0))
            for sh in ordered:
                if sh.shape_type == 6 and hasattr(sh, "shapes"):  # group
                    yield from walk(sh.shapes)
                else:
                    yield sh

        for shape in walk(slide.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if not getattr(shape, "has_text_frame", False):
                continue
            is_body = False
            try:
                is_body = shape.is_placeholder and shape.placeholder_format.type in (2, 7)  # BODY, OBJECT
            except Exception:
                pass
            paras = [p for p in shape.text_frame.paragraphs if p.text.strip()]
            for para in paras:
                para_text = para.text.strip()
                level = para.level or 0
                if level > 0 or (is_body and len(paras) > 1):
                    bullet_points.append(f"{'  ' * max(level - 1, 0)}- {para_text}")
                else:
                    text_blocks.append(para_text)

        # Get slide title
        if slide.shapes.title is not None:
            try:
                title = slide.shapes.title.text.strip()
                # Remove title text from text_blocks to avoid duplication
                text_blocks = [t for t in text_blocks if t != title]
            except Exception:
                pass

        if not title:
            title = f"Slide {slide_num}"

        # Speaker notes
        notes = ""
        try:
            if slide.has_notes_slide and slide.notes_slide:
                notes_tf = slide.notes_slide.notes_text_frame
                if notes_tf:
                    notes = notes_tf.text.strip()
        except Exception:
            pass

        return {
            "slide_num": slide_num,
            "title": title,
            "text_blocks": text_blocks,
            "bullet_points": bullet_points,
            "tables": [],     # populated later
            "notes": notes,
            "images": [],     # populated later
            "charts": [],     # populated later
        }

    def _extract_tables_from_slide(self, slide) -> list[list[list[str]]]:
        """
        Extract tables from a slide.

        Args:
            slide: A pptx Slide object.

        Returns:
            List of tables, each table being a list of rows of cell strings.
        """
        tables: list[list[list[str]]] = []

        for shape in slide.shapes:
            if shape.has_table:
                table = shape.table
                rows_data: list[list[str]] = []
                for row in table.rows:
                    row_cells: list[str] = []
                    for cell in row.cells:
                        cell_text = cell.text.strip() if cell.text else ""
                        row_cells.append(cell_text)
                    rows_data.append(row_cells)
                if rows_data:
                    tables.append(rows_data)

        return tables

    def _extract_images_from_slide(
        self,
        slide,
        slide_num: int,
        assets_dir: str,
        dup_tracker: "DuplicateTracker",
    ) -> list[dict]:
        """
        Extract images from a slide, save to assets_dir with deduplication.

        Args:
            slide:       A pptx Slide object.
            slide_num:   1-based slide number.
            assets_dir:  Directory to save images into.
            dup_tracker: DuplicateTracker for deduplication.

        Returns:
            List of dicts: {path, width, height, hash}.
        """
        images: list[dict] = []
        img_counter = 0

        for shape in slide.shapes:
            # Check for picture shapes
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    image = shape.image
                    image_bytes = image.blob
                    content_type = image.content_type
                    ext = self._content_type_to_ext(content_type)

                    # Get dimensions
                    width = shape.width
                    height = shape.height
                    # Convert EMU to pixels (approx)
                    width_px = int(width / 914400 * 96) if width else 0
                    height_px = int(height / 914400 * 96) if height else 0

                    # Compute hash for deduplication
                    img_hash = hashlib.new(HASH_ALGORITHM, image_bytes).hexdigest()

                    if dup_tracker.is_duplicate(img_hash):
                        existing = dup_tracker.get_path(img_hash)
                        if existing:
                            images.append(
                                {
                                    "path": existing,
                                    "width": width_px,
                                    "height": height_px,
                                    "hash": img_hash,
                                }
                            )
                        continue

                    img_counter += 1
                    filename = f"slide_{slide_num:02d}_image_{img_counter:02d}.{ext}"
                    img_path = os.path.join(assets_dir, filename)

                    with open(img_path, "wb") as f:
                        f.write(image_bytes)

                    dup_tracker.register(img_hash, img_path)

                    images.append(
                        {
                            "path": img_path,
                            "width": width_px,
                            "height": height_px,
                            "hash": img_hash,
                        }
                    )
                except Exception:
                    continue

            # Check for group shapes that may contain images
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                try:
                    for sub_shape in shape.shapes:
                        if sub_shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                            image = sub_shape.image
                            image_bytes = image.blob
                            content_type = image.content_type
                            ext = self._content_type_to_ext(content_type)

                            img_hash = hashlib.new(HASH_ALGORITHM, image_bytes).hexdigest()

                            if dup_tracker.is_duplicate(img_hash):
                                existing = dup_tracker.get_path(img_hash)
                                if existing:
                                    images.append({
                                        "path": existing,
                                        "width": 0,
                                        "height": 0,
                                        "hash": img_hash,
                                    })
                                continue

                            img_counter += 1
                            filename = f"slide_{slide_num:02d}_image_{img_counter:02d}.{ext}"
                            img_path = os.path.join(assets_dir, filename)

                            with open(img_path, "wb") as f:
                                f.write(image_bytes)

                            dup_tracker.register(img_hash, img_path)
                            images.append({
                                "path": img_path,
                                "width": 0,
                                "height": 0,
                                "hash": img_hash,
                            })
                except Exception:
                    continue

        return images

    def _extract_chart_data(self, slide) -> list[dict]:
        """
        Attempt to extract chart data from a slide.

        Args:
            slide: A pptx Slide object.

        Returns:
            List of dicts with chart info: {title, chart_type, categories, series}.
        """
        charts: list[dict] = []

        for shape in slide.shapes:
            if shape.has_chart:
                try:
                    chart = shape.chart
                    chart_info: dict = {
                        "title": "",
                        "chart_type": "",
                        "categories": [],
                        "series": [],
                    }

                    # Chart title
                    try:
                        if chart.has_title and chart.chart_title:
                            chart_info["title"] = chart.chart_title.text_frame.text.strip()
                    except Exception:
                        pass

                    # Chart type
                    try:
                        chart_info["chart_type"] = str(chart.chart_type)
                    except Exception:
                        chart_info["chart_type"] = "unknown"

                    # Categories
                    try:
                        plot = chart.plots[0]
                        categories = [
                            str(cat) for cat in plot.categories
                        ]
                        chart_info["categories"] = categories
                    except Exception:
                        pass

                    # Series data
                    try:
                        for series in chart.series:
                            series_data: dict = {
                                "name": "",
                                "values": [],
                            }
                            try:
                                series_data["name"] = series.tx.text if series.tx else ""
                            except Exception:
                                pass
                            try:
                                series_data["values"] = [
                                    float(v) if v is not None else 0.0
                                    for v in series.values
                                ]
                            except Exception:
                                pass
                            chart_info["series"].append(series_data)
                    except Exception:
                        pass

                    charts.append(chart_info)
                except Exception:
                    continue

        return charts

    def _build_markdown(self, slides_data: list[dict], pres_title: str = "") -> str:
        """
        Build the final structured Markdown from all slide data.

        Format:
            # Presentation Title

            ## Slide 1: [Title]

            [Content]

            [IMAGE: assets/slide_01_image_01.png]

            > Speaker Notes: [notes text]

        Args:
            slides_data: List of per-slide extraction dicts.
            pres_title:  Overall presentation title.

        Returns:
            Structured Markdown string.
        """
        md_parts: list[str] = []
        pres = self.optimization_mode == OptimizationMode.PRESERVATION
        compact = not pres

        if pres_title:
            md_parts.append(f"# {pres_title}")

        for sd in slides_data:
            n = sd["slide_num"]
            title = sd.get("title") or f"Slide {n}"
            md_parts.append(f"## Slide {n}: {title}" if pres else f"## {n}. {title}")

            body = list(sd.get("text_blocks", []))
            if sd.get("bullet_points"):
                body.append("\n".join(sd["bullet_points"]))
            for table in sd.get("tables", []):
                body.append(self._table_to_markdown(table))
            for chart in sd.get("charts", []):
                body.append(self._chart_to_markdown(chart))
            for img in sd.get("images", []):
                body.append(f"![{os.path.basename(img['path'])}]({img['path']})")
            if sd.get("notes"):
                body.append(f"> Notes: {sd['notes']}" if compact else f"> Speaker Notes: {sd['notes']}")
            if body:
                md_parts.append("\n\n".join(body))

        return "\n\n".join(md_parts)

    def _table_to_markdown(self, table: list[list[str]]) -> str:
        """Convert a table (list of rows) to a Markdown table string."""
        return render_table(table, compact=self.optimization_mode != OptimizationMode.PRESERVATION)

    def _chart_to_markdown(self, chart: dict) -> str:
        """
        Render chart data as a Markdown table.

        Args:
            chart: Dict with {title, chart_type, categories, series}.

        Returns:
            Markdown representation of the chart data.
        """
        title = chart.get("title") or "Chart"
        categories = chart.get("categories", [])
        series_list = chart.get("series", [])
        head = f"**{title}** ({chart.get('chart_type', 'chart')})"
        if not categories and not series_list:
            return head + " [data not extractable]"
        rows = [["Category"] + [s_.get("name", f"Series {i+1}") for i, s_ in enumerate(series_list)]]
        for i, cat in enumerate(categories):
            row = [str(cat)]
            for ser in series_list:
                vals = ser.get("values", [])
                row.append(str(vals[i]) if i < len(vals) else "")
            rows.append(row)
        return head + "\n" + render_table(rows, compact=self.optimization_mode != OptimizationMode.PRESERVATION)

    def _content_type_to_ext(self, content_type: str) -> str:
        """Map MIME content type to file extension."""
        mapping = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/gif": "gif",
            "image/bmp": "bmp",
            "image/tiff": "tiff",
            "image/svg+xml": "svg",
            "image/x-emf": "emf",
            "image/x-wmf": "wmf",
        }
        return mapping.get(content_type, "png")

    def _apply_optimization(self, text: str, mode: str) -> str:
        """
        Apply optimization to the Markdown text based on the selected mode.

        Args:
            text: The raw Markdown text.
            mode: Optimization mode string.

        Returns:
            Optimized text.
        """
        import re

        if mode == OptimizationMode.PRESERVATION:
            text = collapse_blank_lines(text)
            return text

        if mode == OptimizationMode.BALANCED:
            text = normalize_whitespace(text)
            text = collapse_blank_lines(text)
            text = strip_excessive_newlines(text)
            return text

        if mode == OptimizationMode.MAX_COMPRESSION:
            text = normalize_whitespace(text)
            text = collapse_blank_lines(text)
            text = strip_excessive_newlines(text)

            # Remove redundant slide markers for empty slides
            text = re.sub(
                r"## Slide \d+: Slide \d+\n\n(?=## |\Z)", "", text
            )

            # Collapse multiple blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = "\n".join(line.rstrip() for line in text.split("\n"))
            return text.strip()

        # Fallback: balanced
        text = normalize_whitespace(text)
        text = collapse_blank_lines(text)
        return text
