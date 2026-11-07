"""
TOKENFORGE — Export Engine
==========================
Manages output generation, folder hierarchy, JSON reports, summary Markdown,
and complete ZIP bundling for TOKENFORGE.
"""

import os
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config import (
    OUTPUT_ROOT,
    OPTIMIZED_DIR,
    ASSETS_DIR,
    REPORTS_DIR,
    ORIGINALS_DIR,
    SUMMARY_FILE,
    APP_NAME,
    APP_VERSION,
)
from utils.file_utils import create_output_structure, copy_file_safe


class ExportEngine:
    """Manages files, JSON reports, summary reports, and ZIP exports."""

    def __init__(self, base_output_dir: str | Path | None = None):
        """
        Initialize the ExportEngine.

        Args:
            base_output_dir: Root directory for output. Defaults to ./TOKENFORGE_OUTPUT.
        """
        if base_output_dir is None:
            self.base_dir = Path.cwd() / OUTPUT_ROOT
        else:
            self.base_dir = Path(base_output_dir)

        # Output folder paths
        self.paths = create_output_structure(self.base_dir)
        self.base_dir = self.paths["root"]
        self.optimized_dir = self.paths["optimized"]
        self.assets_dir = self.paths["assets"]
        self.reports_dir = self.paths["reports"]
        self.originals_dir = self.paths["originals"]

    def get_output_paths(self) -> dict[str, Path]:
        """Return a mapping of output directories."""
        return self.paths

    def export_result(self, result: dict, include_original: bool = False) -> str:
        """
        Ensure the optimized markdown file is in the optimized/ folder
        and optionally copy original files into originals/.

        Args:
            result:           Processor result dictionary.
            include_original: Whether to copy the original source document.

        Returns:
            Path to the final optimized file.
        """
        source_path = Path(result["source_file"])
        target_md_path = Path(result.get("output_file") or (self.optimized_dir / f"{source_path.stem}.md"))
        target_md_path.parent.mkdir(parents=True, exist_ok=True)

        # Write or copy optimized text
        with open(target_md_path, "w", encoding="utf-8") as f:
            f.write(result["optimized_text"])

        # Optionally copy original
        if include_original and source_path.exists():
            orig_dest = self.originals_dir / source_path.name
            copy_file_safe(source_path, orig_dest)

        return str(target_md_path)

    def generate_compression_report(self, results: list[dict]) -> str:
        """
        Generate reports/compression_report.json with per-document and aggregate stats.

        Returns:
            Absolute path to compression_report.json.
        """
        total_original_tokens = sum(r.get("original_tokens", 0) for r in results)
        total_optimized_tokens = sum(r.get("optimized_tokens", 0) for r in results)
        total_tokens_saved = total_original_tokens - total_optimized_tokens
        overall_reduction = (
            round((total_tokens_saved / total_original_tokens) * 100, 2)
            if total_original_tokens > 0
            else 0.0
        )

        report_data = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_documents": len(results),
                "total_original_tokens": total_original_tokens,
                "total_optimized_tokens": total_optimized_tokens,
                "total_tokens_saved": total_tokens_saved,
                "overall_reduction_percentage": overall_reduction,
                "total_processing_time_sec": round(
                    sum(r.get("processing_time", 0.0) for r in results), 2
                ),
            },
            "documents": [
                {
                    "source_file": Path(r["source_file"]).name,
                    "output_file": Path(r.get("output_file", "")).name,
                    "format_type": r.get("format_type", "markdown"),
                    "original_tokens": r.get("original_tokens", 0),
                    "optimized_tokens": r.get("optimized_tokens", 0),
                    "tokens_saved": r.get("tokens_saved", 0),
                    "reduction_percentage": r.get("reduction_pct", 0.0),
                    "images_extracted": len(r.get("images_extracted", [])),
                    "tables_found": r.get("tables_found", 0),
                    "processing_time_sec": r.get("processing_time", 0.0),
                    "warnings": r.get("warnings", []),
                }
                for r in results
            ],
        }

        report_file = self.reports_dir / "compression_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        return str(report_file)

    def generate_validation_report(self, validations: list[dict]) -> str:
        """
        Generate reports/validation_report.json with quality checks and preservation scores.

        Returns:
            Absolute path to validation_report.json.
        """
        report_data = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_validated": len(validations),
                "passed": sum(1 for v in validations if v.get("status") == "pass"),
                "warnings": sum(1 for v in validations if v.get("status") == "warning"),
                "failed": sum(1 for v in validations if v.get("status") == "fail"),
                "average_preservation_score": round(
                    sum(v.get("preservation_score", 1.0) for v in validations)
                    / max(1, len(validations)),
                    3,
                ),
            },
            "validations": validations,
        }

        report_file = self.reports_dir / "validation_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        return str(report_file)

    def generate_summary(
        self, results: list[dict], validations: list[dict]
    ) -> str:
        """
        Generate root TOKENFORGE_SUMMARY.md with comprehensive markdown summary.

        Returns:
            Absolute path to TOKENFORGE_SUMMARY.md.
        """
        total_orig = sum(r.get("original_tokens", 0) for r in results)
        total_opt = sum(r.get("optimized_tokens", 0) for r in results)
        saved = total_orig - total_opt
        pct = round((saved / total_orig) * 100, 2) if total_orig > 0 else 0.0
        total_time = round(sum(r.get("processing_time", 0.0) for r in results), 2)

        summary_lines = [
            f"# {APP_NAME} Processing Summary",
            f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
            "## Aggregate Token Metrics\n",
            f"- **Documents Processed:** {len(results)}",
            f"- **Original Tokens:** {total_orig:,}",
            f"- **Optimized Tokens:** {total_opt:,}",
            f"- **Total Tokens Saved:** {saved:,} (**{pct}%** reduction)",
            f"- **Total Processing Time:** {total_time:.2f} seconds\n",
            "## Document Breakdown\n",
            "| Document | Format | Original | Optimized | Saved | Reduction | Status |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
        ]

        for i, r in enumerate(results):
            name = Path(r["source_file"]).name
            fmt = r.get("format_type", "markdown")
            o_tok = r.get("original_tokens", 0)
            opt_tok = r.get("optimized_tokens", 0)
            s_tok = r.get("tokens_saved", 0)
            red = r.get("reduction_pct", 0.0)
            val = validations[i] if i < len(validations) else {}
            status = val.get("status", "pass").upper()
            summary_lines.append(
                f"| `{name}` | {fmt} | {o_tok:,} | {opt_tok:,} | {s_tok:,} | {red:.1f}% | {status} |"
            )

        summary_lines.extend([
            "\n## Output Structure\n",
            "- `optimized/` : Clean, token-optimized Markdown files ready for LLM upload.",
            "- `assets/` : Preserved diagrams, charts, and document images (referenced relatively).",
            "- `reports/` : Detailed machine-readable JSON compression and validation reports.",
            "- `originals/` : Source documents (if user opted to include them).\n",
            "---\n*TOKENFORGE — Convert documents into token-efficient, LLM-ready content.*",
        ])

        summary_path = self.base_dir / SUMMARY_FILE
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))

        return str(summary_path)

    def create_zip_export(self, target_zip_path: str | Path | None = None) -> str:
        """
        Create a single ZIP bundle of the complete TOKENFORGE_OUTPUT directory.

        Returns:
            Absolute path to the created .zip archive.
        """
        if target_zip_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_zip_path = self.base_dir.parent / f"TOKENFORGE_BUNDLE_{timestamp}.zip"
        else:
            target_zip_path = Path(target_zip_path)

        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(self.base_dir):
                for file in files:
                    file_path = Path(root) / file
                    # Store relative path inside zip
                    arcname = file_path.relative_to(self.base_dir)
                    zipf.write(file_path, arcname)

        return str(target_zip_path)

