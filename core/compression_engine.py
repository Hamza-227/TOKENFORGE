"""
TOKENFORGE — Compression Engine
================================
Token-aware text optimization engine.  Generates multiple compact
representations of input text and selects the best one according to
the chosen optimization mode.
"""

import re
import textwrap
from collections import Counter

from core.token_counter import TokenCounter
from config import OptimizationMode


class CompressionEngine:
    """Generate and select the most token-efficient text representation."""

    # Filler words removed only in max_compression mode
    _FILLER_WORDS = {
        "actually", "basically", "certainly", "clearly", "definitely",
        "essentially", "evidently", "furthermore", "generally", "however",
        "importantly", "indeed", "moreover", "nevertheless", "obviously",
        "particularly", "presumably", "primarily", "significantly",
        "specifically", "subsequently", "therefore", "ultimately",
        "very", "really", "quite", "rather", "somewhat", "just",
    }

    # Common abbreviations for aggressive compaction
    _ABBREVIATIONS = {
        "information": "info",
        "approximately": "approx.",
        "application": "app",
        "configuration": "config",
        "environment": "env",
        "management": "mgmt",
        "development": "dev",
        "organization": "org",
        "documentation": "docs",
        "reference": "ref",
        "maximum": "max",
        "minimum": "min",
        "average": "avg",
        "number": "no.",
        "department": "dept",
        "administration": "admin",
        "specification": "spec",
        "implementation": "impl",
        "requirement": "req",
        "performance": "perf",
    }

    def __init__(self, optimization_mode: str = "balanced"):
        """
        Args:
            optimization_mode: One of 'preservation', 'balanced',
                               'max_compression'.
        """
        self.mode = optimization_mode
        self.token_counter = TokenCounter()

    # ── Public API ───────────────────────────────────────────────────────────

    def optimize(self, text: str, content_type: str = "narrative") -> dict:
        """
        Produce multiple representations, measure tokens, and select the
        best one for the current mode.

        Args:
            text:         Source text to optimise.
            content_type: Hint — ``'narrative'``, ``'tabular'``, ``'mixed'``.

        Returns:
            Dict with ``selected_format``, ``selected_text``,
            ``representations``, token stats, and ``reduction_pct``.
        """
        if not text or not text.strip():
            return self._empty_result()

        # 1.  Generate representations
        representations: dict[str, str] = {}

        representations["original"] = text
        representations["cleaned"] = self._clean_text(text)
        representations["structured_markdown"] = self._to_structured_markdown(text)
        representations["compact_markdown"] = self._to_compact_markdown(text)

        # Tabular conversion (optional)
        if content_type in ("tabular", "mixed"):
            csv_text = self._to_compact_csv(text)
            if csv_text is not None:
                representations["csv"] = csv_text

        # 2.  Count tokens for each
        token_counts: dict[str, int] = {}
        for name, rep_text in representations.items():
            token_counts[name] = self.token_counter.count(rep_text)

        # 3.  Select best
        selected_format, selected_text = self._select_best(
            representations, self.mode
        )

        original_tokens = token_counts.get("original", 0)
        optimized_tokens = token_counts.get(selected_format, 0)
        tokens_saved = max(original_tokens - optimized_tokens, 0)
        reduction_pct = round(
            (tokens_saved / original_tokens * 100) if original_tokens > 0 else 0.0, 2
        )

        # 4.  Build representation summaries
        rep_summaries = {
            name: {"tokens": token_counts[name], "length": len(r_text)}
            for name, r_text in representations.items()
        }

        return {
            "selected_format": selected_format,
            "selected_text": selected_text,
            "representations": rep_summaries,
            "original_tokens": original_tokens,
            "optimized_tokens": optimized_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
        }

    # ── Text transformations ─────────────────────────────────────────────────

    def _clean_text(self, text: str) -> str:
        """
        Normalise whitespace, strip control characters, and remove common
        extraction artefacts (page numbers, headers/footers).
        """
        # Remove null bytes and other control chars (keep newlines/tabs)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Collapse runs of blank lines into at most two
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # Normalise horizontal whitespace (spaces/tabs) within lines
        lines = cleaned.splitlines()
        normalised: list[str] = []
        for line in lines:
            stripped = re.sub(r"[ \t]+", " ", line).strip()
            normalised.append(stripped)
        cleaned = "\n".join(normalised)

        # Remove explicit page-number markers only ("Page 3", "Page 3 of 10",
        # "- 3 -").  Bare numbers are NEVER removed: they may be real data.
        if self.mode != OptimizationMode.PRESERVATION:
            cleaned = re.sub(
                r"(?im)^\s*(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|-\s*\d+\s*-)\s*$",
                "",
                cleaned,
            )
            # Remove exact duplicate paragraphs / repeated boilerplate lines
            cleaned = self._remove_redundancy(cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def _to_structured_markdown(self, text: str) -> str:
        """
        Add lightweight Markdown structure: detect headings, organise
        paragraphs, identify list items.
        """
        cleaned = self._clean_text(text)
        lines = cleaned.splitlines()
        output: list[str] = []
        in_list = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_list:
                    in_list = False
                output.append("")
                continue

            # Already a Markdown heading
            if stripped.startswith("#"):
                output.append(stripped)
                continue

            # Heuristic: short ALL-CAPS line → heading
            if (
                stripped.isupper()
                and len(stripped) < 80
                and not stripped.startswith(("-", "*", "•"))
            ):
                output.append(f"## {stripped.title()}")
                continue

            # Heuristic: line ending with colon, short, no period → heading
            if (
                stripped.endswith(":")
                and len(stripped) < 60
                and "." not in stripped
            ):
                heading_text = stripped.rstrip(":")
                output.append(f"### {heading_text}")
                continue

            # Detect list items
            if re.match(r"^[\-\*•]\s", stripped):
                output.append(f"- {stripped.lstrip('-*• ').strip()}")
                in_list = True
                continue
            if re.match(r"^\d+[\.\)]\s", stripped):
                output.append(stripped)
                in_list = True
                continue

            # Regular paragraph text
            output.append(stripped)

        # Collapse excessive blank lines
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(output))
        return result.strip()

    def _to_compact_markdown(self, text: str) -> str:
        """
        Aggressive compaction: remove filler words, apply abbreviations,
        compress whitespace, compact list formatting.
        """
        compact = self._to_structured_markdown(text)
        compact, protected = self._protect(compact)

        # Remove filler words (case-insensitive, whole words)
        for word in self._FILLER_WORDS:
            pattern = re.compile(rf"\b{re.escape(word)}\b,?\s*", re.IGNORECASE)
            compact = pattern.sub("", compact)

        # Apply abbreviations (lower-case matches only, so names/titles stay intact)
        for long_form, short in self._ABBREVIATIONS.items():
            compact = re.sub(rf"\b{re.escape(long_form)}\b", short, compact)
        compact = self._restore(compact, protected)

        # Collapse multiple spaces created by removals
        compact = re.sub(r"  +", " ", compact)

        # Shorten list items: remove trailing periods
        lines = compact.splitlines()
        shortened: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and stripped.endswith("."):
                stripped = stripped[:-1]
            shortened.append(stripped)
        compact = "\n".join(shortened)

        # Remove single-sentence paragraphs that are purely transitional
        compact = re.sub(
            r"(?m)^(In this section|As mentioned|As noted|See below|The following)[^\n]*\n",
            "",
            compact,
            flags=re.IGNORECASE,
        )

        compact = re.sub(r"\n{3,}", "\n\n", compact)
        return compact.strip()

    # URLs, e-mails, code and inline code must never be altered.
    _PROTECT_RE = re.compile(
        r"```.*?```|`[^`\n]+`|https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.-]+",
        re.DOTALL,
    )

    def _protect(self, text: str):
        saved: list[str] = []

        def _sub(m):
            saved.append(m.group(0))
            return f"\uE000{len(saved) - 1}\uE001"

        return self._PROTECT_RE.sub(_sub, text), saved

    @staticmethod
    def _restore(text: str, saved: list[str]) -> str:
        return re.sub(r"\uE000(\d+)\uE001", lambda m: saved[int(m.group(1))], text)

    def _to_compact_csv(self, text: str) -> str | None:
        """
        If the text appears to contain tabular data, convert it to CSV.
        Returns ``None`` when no table is detected.
        """
        lines = text.strip().splitlines()
        # Heuristic: tabular data has consistent delimiter counts
        # Try tab, pipe, and multi-space as delimiters
        for delimiter, sep_name in [("\t", "\t"), ("|", "|"), ("  ", ",")]:
            # Count fields per line
            field_counts: list[int] = []
            data_lines: list[str] = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if delimiter == "|":
                    # Remove leading/trailing pipes
                    stripped = stripped.strip("|")
                parts = stripped.split(delimiter)
                if len(parts) >= 2:
                    field_counts.append(len(parts))
                    data_lines.append(stripped)

            if len(data_lines) < 3:
                continue

            # Check consistency: most common field count should cover > 60%
            counter = Counter(field_counts)
            most_common_count, freq = counter.most_common(1)[0]
            if freq / len(field_counts) < 0.6 or most_common_count < 2:
                continue

            # Build CSV
            csv_lines: list[str] = []
            for dl in data_lines:
                if delimiter == "|":
                    dl = dl.strip("|")
                cells = [c.strip().strip("-").strip() for c in dl.split(delimiter)]
                # Skip separator rows (all dashes/empty)
                if all(re.match(r"^[\-:=\s]*$", c) for c in cells):
                    continue
                csv_lines.append(",".join(cells))

            if len(csv_lines) >= 2:
                return "\n".join(csv_lines)

        return None

    def _remove_redundancy(self, text: str) -> str:
        """
        Detect and remove repeated phrases or paragraphs.
        """
        paragraphs = re.split(r"\n{2,}", text)
        if len(paragraphs) <= 1:
            return text

        seen: set[str] = set()
        unique: list[str] = []
        for para in paragraphs:
            normalised = re.sub(r"\s+", " ", para).strip().lower()
            if not normalised:
                continue
            if normalised in seen:
                continue
            seen.add(normalised)
            unique.append(para)

        # Also detect repeated lines within the text
        lines = "\n\n".join(unique).splitlines()
        line_counts: Counter = Counter()
        for line in lines:
            key = line.strip().lower()
            if key:
                line_counts[key] += 1

        # Remove lines that appear more than 3 times (likely headers/footers)
        if any(c > 3 for c in line_counts.values()):
            repeated = {
                k for k, c in line_counts.items()
                if c > 3 and len(k) > 12 and "|" not in k and "," not in k
                and not re.match(r"^[\-=*_#\s]+$", k)
            }
            lines = [l for l in lines if l.strip().lower() not in repeated]

        return "\n".join(lines)

    def _select_best(
        self, representations: dict[str, str], mode: str
    ) -> tuple[str, str]:
        """
        Select the best representation based on the optimisation mode.

        Returns:
            Tuple of ``(format_name, text)``.
        """
        if mode == OptimizationMode.PRESERVATION:
            # Minimal changes — just cleaned version
            key = "cleaned"
        elif mode == OptimizationMode.BALANCED:
            key = "structured_markdown"
        elif mode == OptimizationMode.MAX_COMPRESSION:
            # Pick the smallest token representation
            best_key = "compact_markdown"
            best_tokens = self.token_counter.count(
                representations.get("compact_markdown", "")
            )
            for candidate in ("csv",):
                if candidate in representations:
                    t = self.token_counter.count(representations[candidate])
                    if t < best_tokens and t > 0:
                        best_tokens = t
                        best_key = candidate
            key = best_key
        else:
            # Unknown mode → balanced as fallback
            key = "structured_markdown"

        text = representations.get(key, representations.get("cleaned", ""))

        # Safety net: an "optimizer" must never make the document bigger.
        # Fall back to the cheapest candidate that is not larger than the source.
        orig_t = self.token_counter.count(representations.get("original", ""))
        if self.token_counter.count(text) > orig_t:
            best = min(
                (k for k in ("cleaned", "structured_markdown", "original") if k in representations),
                key=lambda k: self.token_counter.count(representations[k]),
            )
            key, text = best, representations[best]
        return key, text

    def apply_mode_optimizations(self, text: str, mode: str) -> str:
        """
        Apply mode-specific post-processing to already-optimised text.

        Args:
            text: The text to further optimise.
            mode: Optimisation mode string.

        Returns:
            The post-processed text.
        """
        if mode == OptimizationMode.PRESERVATION:
            # Only normalise whitespace
            return re.sub(r"\n{3,}", "\n\n", text).strip()

        if mode == OptimizationMode.BALANCED:
            # Light cleanup
            result = re.sub(r"\n{3,}", "\n\n", text)
            # Ensure headings have blank line before them
            result = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", result)
            return result.strip()

        if mode == OptimizationMode.MAX_COMPRESSION:
            # Aggressive: remove filler, abbreviate, compress blank lines
            result = text
            for word in self._FILLER_WORDS:
                pattern = re.compile(rf"\b{re.escape(word)}\b\s*", re.IGNORECASE)
                result = pattern.sub("", result)
            for long_form, short in self._ABBREVIATIONS.items():
                pattern = re.compile(rf"\b{re.escape(long_form)}\b", re.IGNORECASE)
                result = pattern.sub(short, result)
            result = re.sub(r"  +", " ", result)
            result = re.sub(r"\n{2,}", "\n", result)
            return result.strip()

        return text

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _empty_result(self) -> dict:
        """Return a result dict for empty/blank input."""
        return {
            "selected_format": "original",
            "selected_text": "",
            "representations": {},
            "original_tokens": 0,
            "optimized_tokens": 0,
            "tokens_saved": 0,
            "reduction_pct": 0.0,
        }
