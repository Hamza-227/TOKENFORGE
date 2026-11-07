"""
TOKENFORGE — Excel & CSV Processor
===================================
Extracts data from Excel spreadsheets (.xlsx) and CSV files.
Applies intelligent representation selection (Markdown tables vs compact CSV)
to minimize LLM token usage while preserving numerical precision and structure.
"""

import os
import io
import time
import csv
from pathlib import Path

try:
    import pandas as pd
    import openpyxl
except ImportError:
    pd = None
    openpyxl = None

from config import (
    OptimizationMode,
)
from core.token_counter import TokenCounter
from utils.text_utils import (
    normalize_whitespace,
    collapse_blank_lines,
    compact_table_format,
    render_table,
)


class ExcelProcessor:
    """Process Excel (.xlsx) and CSV (.csv) files into token-optimized formats."""

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Initialize the Excel processor.

        Args:
            optimization_mode: One of 'preservation', 'balanced', 'max_compression'.
        """
        self.optimization_mode = optimization_mode
        self.token_counter = TokenCounter()

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, filepath: str, output_dir: str, assets_dir: str = None) -> dict:
        """
        Main entry point — load spreadsheet, detect structure, optimize, write output.

        Args:
            filepath:   Path to the input .xlsx or .csv file.
            output_dir: Directory for the generated Markdown/CSV.
            assets_dir: Directory for assets (if any).

        Returns:
            Standard TOKENFORGE result dict.
        """
        start_time = time.time()
        warnings: list[str] = []

        if pd is None:
            raise ImportError(
                "pandas is required for Excel/CSV processing. "
                "Install it with: pip install pandas openpyxl"
            )

        filepath = str(filepath)
        output_dir = str(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        ext = Path(filepath).suffix.lower()
        base_name = Path(filepath).stem

        # ── Parse data ────────────────────────────────────────────────────────
        sheets_data = {}  # {sheet_name: DataFrame}
        try:
            if ext == ".csv":
                df = self._read_csv_safe(filepath)
                sheets_data["Sheet1"] = df
            else:
                excel_file = pd.ExcelFile(filepath, engine="openpyxl")
                for sheet in excel_file.sheet_names:
                    df = excel_file.parse(sheet, header=0)
                    sheets_data[sheet] = df
        except Exception as exc:
            raise RuntimeError(f"Cannot read spreadsheet '{filepath}': {exc}") from exc

        # ── Raw representation for original token baseline ────────────────────
        if ext == ".csv":
            try:
                original_text = Path(filepath).read_text(encoding="utf-8", errors="replace")
            except Exception:
                original_text = self._build_original_raw_representation(sheets_data)
        else:
            original_text = self._build_original_raw_representation(sheets_data)

        self._multi_sheet = len(sheets_data) > 1

        # ── Optimize each sheet & intelligently decide representation ────────
        optimized_sections = []
        total_rows = 0
        total_cols = 0
        format_types_used = []

        for sheet_name, df in sheets_data.items():
            if df.empty or (df.shape[0] == 0 and df.shape[1] == 0):
                continue

            cleaned_df = self._optimize_dataframe(df, self.optimization_mode)
            total_rows += len(cleaned_df)
            total_cols = max(total_cols, len(cleaned_df.columns))

            # Decide representation for this sheet:
            # - Small tables (< 30 rows) -> Markdown table
            # - Large numerical datasets -> compact CSV block
            rep_type, formatted_content = self._format_sheet(
                sheet_name, cleaned_df, self.optimization_mode
            )
            format_types_used.append(rep_type)
            optimized_sections.append(formatted_content)

        # Combine into complete LLM document
        if self.optimization_mode == OptimizationMode.PRESERVATION:
            doc_header = f"# {Path(filepath).name} ({len(sheets_data)} sheet(s), {total_rows} rows)\n\n"
        else:
            doc_header = ""
        optimized_text = doc_header + "\n\n".join(optimized_sections)

        # ── Token counting ────────────────────────────────────────────────────
        original_tokens = self.token_counter.count(original_text)
        optimized_tokens = self.token_counter.count(optimized_text)
        tokens_saved = original_tokens - optimized_tokens
        reduction_pct = (
            round((tokens_saved / original_tokens) * 100, 2)
            if original_tokens > 0
            else 0.0
        )

        # ── Write output ──────────────────────────────────────────────────────
        # Even if CSV representation was chosen for large tables, we present it in
        # a markdown file or markdown with codeblocks for AI platform ingestion
        output_file = os.path.join(output_dir, f"{base_name}.md")
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(optimized_text)
        except Exception as exc:
            warnings.append(f"Failed to write output file: {exc}")

        primary_format = "markdown"
        if all(fmt == "csv" for fmt in format_types_used) and len(format_types_used) > 0:
            primary_format = "compact_csv"

        processing_time = round(time.time() - start_time, 3)

        return {
            "source_file": filepath,
            "output_file": output_file,
            "format_type": primary_format,
            "original_text": original_text,
            "optimized_text": optimized_text,
            "original_tokens": original_tokens,
            "optimized_tokens": optimized_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
            "images_extracted": [],
            "tables_found": len(sheets_data),
            "pages": len(sheets_data),
            "processing_time": processing_time,
            "warnings": warnings,
            "metadata": {
                "sheets_count": len(sheets_data),
                "total_rows": total_rows,
                "total_columns": total_cols,
                "optimization_mode": self.optimization_mode,
                "formats_selected": list(set(format_types_used)),
            },
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _read_csv_safe(self, filepath: str) -> "pd.DataFrame":
        """Read CSV file with automatic delimiter and encoding fallback."""
        encodings = ["utf-8", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                # First try pandas with auto separator engine
                return pd.read_csv(filepath, encoding=enc, sep=None, engine="python")
            except Exception:
                continue
        # Fallback to standard utf-8
        return pd.read_csv(filepath, encoding="utf-8", on_bad_lines="skip")

    def _build_original_raw_representation(self, sheets: dict[str, "pd.DataFrame"]) -> str:
        """Create baseline string representation of raw unoptimized data."""
        out = []
        for name, df in sheets.items():
            if len(sheets) > 1:
                out.append(f"## {name}")
            out.append(df.to_csv(index=False).strip())
        return "\n".join(out)

    def _optimize_dataframe(self, df: "pd.DataFrame", mode: str) -> "pd.DataFrame":
        """Clean and optimize DataFrame without losing data."""
        df = df.copy()

        # Drop entirely empty rows and columns
        df.dropna(how="all", inplace=True)
        df.dropna(axis=1, how="all", inplace=True)

        # Fill NaNs with empty string
        df.fillna("", inplace=True)

        # Clean string columns: strip trailing/leading spaces
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()

        if mode == OptimizationMode.PRESERVATION:
            return df

        # In Balanced / Max Compression: format floats cleanly (e.g. 12.000 -> 12)
        for col in df.select_dtypes(include=["float"]).columns:
            df[col] = df[col].apply(self._fmt_float)

        return df

    @staticmethod
    def _fmt_float(x) -> str:
        """Lossless compact float: 12.0 -> '12', 3.50 -> '3.5' (no rounding)."""
        try:
            if x == "" or x is None:
                return ""
            f = float(x)
            if f.is_integer() and abs(f) < 1e15:
                return str(int(f))
            return format(f, ".15g")
        except (TypeError, ValueError):
            return str(x)

    def _format_sheet(
        self, sheet_name: str, df: "pd.DataFrame", mode: str
    ) -> tuple[str, str]:
        """
        Intelligently select representation format based on row count and data density.
        Returns (format_type, formatted_markdown_string).
        """
        row_count = len(df)
        col_count = len(df.columns)
        multi = getattr(self, "_multi_sheet", False)

        table_md = self._df_to_markdown_table(df)
        raw_csv = self._df_to_compact_csv(df)
        # Fences only when several sheets share one document (cost ~6 tokens).
        table_csv = f"```csv\n{raw_csv}\n```" if multi else raw_csv

        if mode == OptimizationMode.PRESERVATION:
            rep_type, body = "markdown_table", self._df_to_markdown_table(df, padded=True)
        elif mode == OptimizationMode.MAX_COMPRESSION:
            rep_type, body = "csv", table_csv
        else:  # balanced: whichever representation is really cheaper
            c_md = self.token_counter.count(table_md)
            c_csv = self.token_counter.count(table_csv)
            rep_type, body = ("markdown_table", table_md) if c_md <= c_csv else ("csv", table_csv)

        head = f"## {sheet_name}\n" if multi else ""
        return rep_type, head + body

    def _df_to_markdown_table(self, df: "pd.DataFrame", padded: bool = False) -> str:
        """Convert DataFrame to a Markdown table (compact unless ``padded``)."""
        rows = [[str(c) for c in df.columns]]
        rows += [[str(v) for v in row] for row in df.itertuples(index=False)]
        return render_table(rows, compact=not padded)

    def _df_to_compact_csv(self, df: "pd.DataFrame") -> str:
        """Export DataFrame as clean compact CSV without extra quotes/spaces."""
        output = io.StringIO()
        df.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
        return output.getvalue().strip()

