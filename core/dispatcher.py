"""
TOKENFORGE — Document Dispatcher & Orchestrator
==============================================
Intelligently routes files to their respective specialized processors,
handles text documents, runs validation, and produces standard result objects.
"""

import os
import re
import shutil
import time
from pathlib import Path

from config import SUPPORTED_EXTENSIONS, OptimizationMode
from core.pdf_processor import PDFProcessor
from core.pptx_processor import PPTXProcessor
from core.docx_processor import DOCXProcessor
from core.excel_processor import ExcelProcessor
from core.image_processor import ImageProcessor
from core.compression_engine import CompressionEngine
from core.token_counter import TokenCounter
from core.validation_engine import ValidationEngine
from utils.text_utils import estimate_content_type


def process_document(
    filepath: str | Path,
    output_dir: str | Path,
    assets_dir: str | Path | None = None,
    mode: str = "balanced",
    name_registry: dict | None = None,
) -> dict:
    """
    Route any supported file to its processor and return the result dict.

    Args:
        filepath:   Path to the input file.
        output_dir: Directory where optimized markdown should be written.
        assets_dir: Directory for extracted images.
        mode:       Optimization mode ('preservation', 'balanced', 'max_compression').

    Returns:
        Standard TOKENFORGE result dictionary.
    """
    filepath = Path(filepath)
    output_dir = Path(output_dir)
    ext = filepath.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file format: {ext}")

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_root = Path(assets_dir) if assets_dir else output_dir.parent / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    # Unique name per document: report.pdf + report.docx must not overwrite each other
    registry = name_registry if name_registry is not None else {}
    key = filepath.stem
    if key in registry and registry[key] != str(filepath):
        key = f"{filepath.stem}_{ext.lstrip('.')}"
        n = 2
        while key in registry and registry[key] != str(filepath):
            key = f"{filepath.stem}_{ext.lstrip('.')}_{n}"
            n += 1
    registry[key] = str(filepath)

    doc_assets = assets_root / key
    tmp_dir = output_dir / f".tmp_{key}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        if ext in (".pdf", ".pptx", ".docx", ".xlsx", ".csv", ".png", ".jpg", ".jpeg", ".tiff", ".tif"):
            cls = {
                ".pdf": PDFProcessor, ".pptx": PPTXProcessor, ".docx": DOCXProcessor,
                ".xlsx": ExcelProcessor, ".csv": ExcelProcessor,
            }.get(ext, ImageProcessor)
            result = cls(optimization_mode=mode).process(str(filepath), str(tmp_dir), str(doc_assets))
        elif ext == ".txt":
            result = _process_txt_file(filepath, tmp_dir, mode)
        else:
            raise ValueError(f"No processor registered for {ext}")
    finally:
        pass

    # Move markdown to its final, unique name and make asset links relative
    final_md = output_dir / f"{key}.md"
    text = result["optimized_text"]
    text = _relink_assets(text, doc_assets, final_md.parent)
    final_md.write_text(text, encoding="utf-8")
    result["optimized_text"] = text
    result["output_file"] = str(final_md)
    result["images_extracted"] = [
        os.path.relpath(p, output_dir).replace("\\", "/") if os.path.isabs(str(p)) else str(p)
        for p in result.get("images_extracted", [])
    ]
    if mode != OptimizationMode.PRESERVATION:
        result = _enforce_no_growth(result, final_md, mode)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    try:  # drop empty per-document asset folders
        if doc_assets.exists() and not any(doc_assets.rglob("*")):
            shutil.rmtree(doc_assets, ignore_errors=True)
    except OSError:
        pass
    return result


def _lean_tables(text: str) -> str:
    """Rewrite Markdown tables as plain `a|b|c` rows (no separator row, no outer pipes)."""
    out = []
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("|") and t.endswith("|"):
            if re.fullmatch(r"\|[\s:|\-]+\|", t):
                continue
            out.append(t[1:-1])
        else:
            out.append(line)
    return "\n".join(out)


def _enforce_no_growth(result: dict, final_md: Path, mode: str) -> dict:
    """
    Guarantee that Balanced / Maximum output is never larger than the source text.

    If the structured Markdown costs more tokens than the raw extraction, try
    progressively leaner forms and keep the cheapest one.
    """
    counter = TokenCounter()
    orig_text = result.get("original_text", "")
    orig_tokens = counter.count(orig_text)
    text = result["optimized_text"]
    if orig_tokens == 0 or counter.count(text) <= orig_tokens:
        return result

    candidates = {"markdown": text}
    candidates["markdown (lean tables)"] = _lean_tables(text)
    lean = re.sub(r"\n{3,}", "\n\n", re.sub(r"(?m)^!\[[^\]]*\]\([^)]*\)\s*$", "", candidates["markdown (lean tables)"])).strip()
    candidates["markdown (lean)"] = lean
    try:
        engine = CompressionEngine(optimization_mode=mode)
        plain = engine.optimize(orig_text, content_type="mixed")["selected_text"]
        candidates["plain text"] = plain
    except Exception:
        pass
    candidates["source text"] = re.sub(r"\n{3,}", "\n\n", orig_text).strip()

    best_name, best_text = min(
        ((n, t) for n, t in candidates.items() if t.strip()),
        key=lambda kv: counter.count(kv[1]),
    )
    best_tokens = counter.count(best_text)
    if best_tokens < counter.count(text):
        final_md.write_text(best_text, encoding="utf-8")
        result["optimized_text"] = best_text
        result["format_type"] = best_name
        result.setdefault("warnings", []).append(
            f"Rich Markdown would have been larger than the source, so the leaner '{best_name}' form was used."
        )
    result["optimized_tokens"] = counter.count(result["optimized_text"])
    result["original_tokens"] = orig_tokens
    result["tokens_saved"] = result["original_tokens"] - result["optimized_tokens"]
    result["reduction_pct"] = round(result["tokens_saved"] / orig_tokens * 100, 2)
    return result


def _relink_assets(text: str, doc_assets: Path, md_dir: Path) -> str:
    """Rewrite ![](path) references to portable paths relative to the .md file."""
    def fix(m):
        alt, ref = m.group(1), m.group(2)
        cand = Path(ref)
        if not cand.is_absolute() or not cand.exists():
            found = list(doc_assets.rglob(Path(ref).name)) if doc_assets.exists() else []
            if not found:
                return m.group(0)
            cand = found[0]
        rel = os.path.relpath(cand, md_dir).replace("\\", "/")
        return f"![{alt}]({rel})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", fix, text)


def _process_txt_file(filepath: Path, output_dir: Path, mode: str) -> dict:
    """Process plain text files using CompressionEngine."""
    start_time = time.time()
    counter = TokenCounter()
    engine = CompressionEngine(optimization_mode=mode)

    try:
        raw_text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Cannot read text file '{filepath}': {exc}") from exc

    ctype = estimate_content_type(raw_text)
    comp_res = engine.optimize(raw_text, content_type=ctype)

    optimized_text = comp_res.get("selected_text", raw_text)
    orig_tokens = comp_res.get("original_tokens", counter.count(raw_text))
    opt_tokens = comp_res.get("optimized_tokens", counter.count(optimized_text))
    tokens_saved = max(0, orig_tokens - opt_tokens)
    reduction_pct = (
        round((tokens_saved / orig_tokens) * 100, 2) if orig_tokens > 0 else 0.0
    )

    base_name = filepath.stem
    output_file = output_dir / f"{base_name}.md"
    output_file.write_text(optimized_text, encoding="utf-8")

    return {
        "source_file": str(filepath),
        "output_file": str(output_file),
        "format_type": "markdown",
        "original_text": raw_text,
        "optimized_text": optimized_text,
        "original_tokens": orig_tokens,
        "optimized_tokens": opt_tokens,
        "tokens_saved": tokens_saved,
        "reduction_pct": reduction_pct,
        "images_extracted": [],
        "tables_found": 0,
        "pages": 1,
        "processing_time": round(time.time() - start_time, 3),
        "warnings": [],
        "metadata": {
            "content_type_detected": ctype,
            "selected_representation": comp_res.get("selected_format", "markdown"),
            "optimization_mode": mode,
        },
    }

