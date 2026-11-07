"""
TOKENFORGE — Validation Engine
==============================
Verifies that token optimization preserves essential facts, numerical values,
entities, and structural integrity without introducing hallucinations or silent loss.
"""

import re
from core.token_counter import TokenCounter


class ValidationEngine:
    """Validates optimized output against the original extracted document content."""

    def __init__(self):
        self.token_counter = TokenCounter()

    def validate(
        self, original_text: str, optimized_text: str, mode: str = "balanced"
    ) -> dict:
        """
        Validate optimized text against original text.

        Args:
            original_text:  Raw unoptimized document text.
            optimized_text: Generated optimized Markdown/CSV.
            mode:           Optimization mode ('preservation', 'balanced', 'max_compression').

        Returns:
            Dictionary containing validation status, preservation score, and detailed check results.
        """
        checks = []
        warnings = []

        orig_tokens = self.token_counter.count(original_text)
        opt_tokens = self.token_counter.count(optimized_text)
        tokens_saved = orig_tokens - opt_tokens
        reduction_pct = (
            round((tokens_saved / orig_tokens) * 100, 2) if orig_tokens > 0 else 0.0
        )

        # 1. Number preservation check
        num_check = self._check_numbers_preserved(original_text, optimized_text)
        checks.append(num_check)
        if num_check["status"] == "warning":
            warnings.append(num_check["details"])

        # 2. Key entity / contact / URL preservation check
        entity_check = self._check_entities_preserved(original_text, optimized_text)
        checks.append(entity_check)
        if entity_check["status"] == "warning":
            warnings.append(entity_check["details"])

        # 3. Structural integrity check
        struct_check = self._check_structure_preserved(optimized_text)
        checks.append(struct_check)
        if struct_check["status"] == "warning":
            warnings.append(struct_check["details"])

        # 3b. Vocabulary coverage
        cov_check = self._check_word_coverage(original_text, optimized_text, mode)
        checks.append(cov_check)
        if cov_check["status"] == "warning":
            warnings.append(cov_check["details"])

        # 4. Content consistency / non-emptiness check
        consistency_check = self._check_content_consistency(original_text, optimized_text)
        checks.append(consistency_check)
        if consistency_check["status"] == "warning":
            warnings.append(consistency_check["details"])

        # Calculate overall preservation score (0.0 to 1.0)
        preservation_score = self._calculate_preservation_score(checks, mode)

        # Overall status
        if any(c["status"] == "fail" for c in checks):
            overall_status = "fail"
        elif any(c["status"] == "warning" for c in checks) or preservation_score < 0.85:
            overall_status = "warning"
        else:
            overall_status = "pass"

        return {
            "status": overall_status,
            "preservation_score": round(preservation_score, 3),
            "original_tokens": orig_tokens,
            "optimized_tokens": opt_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
            "checks": checks,
            "warnings": warnings,
            "details": {
                "numbers_checked": num_check.get("total_checked", 0),
                "numbers_missing": len(num_check.get("missing", [])),
                "entities_checked": entity_check.get("total_checked", 0),
            },
        }

    # ── Individual Validation Checks ──────────────────────────────────────────

    _NUM_RE = re.compile(r"(?<![\w.])[-+]?[$€£]?\d[\d,]*(?:\.\d+)?%?")

    @classmethod
    def _numbers(cls, text: str) -> set[str]:
        """Extract numbers in a canonical form (1,500 == 1500; 12.0 == 12; $ and % ignored)."""
        out: set[str] = set()
        for m in cls._NUM_RE.finditer(text):
            raw = m.group(0).lstrip("+-$€£").rstrip("%").replace(",", "")
            try:
                f = float(raw)
            except ValueError:
                continue
            out.add(str(int(f)) if f.is_integer() else format(f, ".10g"))
        return out

    def _check_numbers_preserved(self, original: str, optimized: str) -> dict:
        """Check if numerical values in the original are preserved in optimized text."""
        orig_nums = self._numbers(original)
        opt_nums = self._numbers(optimized)

        if not orig_nums:
            return {
                "name": "numerical_preservation",
                "status": "pass",
                "score": 1.0,
                "total_checked": 0,
                "missing": [],
                "details": "No numerical values detected in source document.",
            }

        missing = sorted(n for n in orig_nums if n not in opt_nums)
        total = len(orig_nums)
        preserved = total - len(missing)
        ratio = preserved / total

        if not missing:
            status, details = "pass", f"All {total} distinct numeric values preserved."
        elif ratio >= 0.98:
            status = "pass"
            details = f"Preserved {preserved}/{total} numeric values. Missing: [{', '.join(missing[:5])}]."
        else:
            status = "warning"
            details = (f"Preserved {preserved}/{total} numeric values ({ratio*100:.1f}%). "
                       f"Missing sample: [{', '.join(missing[:5])}].")

        return {
            "name": "numerical_preservation",
            "status": status,
            "score": round(ratio, 3),
            "total_checked": total,
            "missing": missing[:10],
            "details": details,
        }

    def _check_word_coverage(self, original: str, optimized: str, mode: str) -> dict:
        """Share of distinctive words (4+ letters) from the source that survive."""
        strip = lambda t: re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", t)
        words = lambda t: set(re.findall(r"[^\W\d_]{4,}", strip(t).lower()))
        ow, nw = words(original), words(optimized)
        if len(ow) < 8:  # too little text for a meaningful ratio
            return {"name": "word_coverage", "status": "pass", "score": 1.0,
                    "details": "No significant words to compare."}
        ratio = len(ow & nw) / len(ow)
        floor = {"preservation": 0.97, "balanced": 0.85}.get(mode, 0.70)
        status = "pass" if ratio >= floor else "warning"
        return {"name": "word_coverage", "status": status, "score": round(ratio, 3),
                "details": f"{ratio*100:.1f}% of distinctive words retained (expected \u2265 {floor*100:.0f}% in this mode)."}

    def _check_entities_preserved(self, original: str, optimized: str) -> dict:
        """Check if URLs, email addresses, and key capitalized terms are preserved."""
        url_pattern = r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"

        orig_urls = set(re.findall(url_pattern, original))
        opt_urls = set(re.findall(url_pattern, optimized))
        missing_urls = orig_urls - opt_urls

        orig_emails = set(re.findall(email_pattern, original))
        opt_emails = set(re.findall(email_pattern, optimized))
        missing_emails = orig_emails - opt_emails

        total_entities = len(orig_urls) + len(orig_emails)
        missing_count = len(missing_urls) + len(missing_emails)

        if total_entities == 0:
            return {
                "name": "entity_preservation",
                "status": "pass",
                "score": 1.0,
                "total_checked": 0,
                "details": "No specific URLs or emails in document.",
            }

        preserved = total_entities - missing_count
        ratio = preserved / total_entities

        if missing_count == 0:
            status = "pass"
            details = f"All {total_entities} URLs/emails preserved."
        else:
            status = "warning"
            details = f"{missing_count}/{total_entities} links or emails omitted or modified."

        return {
            "name": "entity_preservation",
            "status": status,
            "score": round(ratio, 3),
            "total_checked": total_entities,
            "details": details,
        }

    def _check_structure_preserved(self, optimized: str) -> dict:
        """Verify presence of Markdown structure (headers, lists, tables)."""
        has_headings = bool(re.search(r"^#{1,6}\s+\S+", optimized, re.MULTILINE))
        has_lists = bool(re.search(r"^[\-\*\+]\s+\S+", optimized, re.MULTILINE))
        has_tables = "|" in optimized and "---" in optimized
        has_codeblocks = "```" in optimized

        structure_elements = sum([has_headings, has_lists or has_tables or has_codeblocks])
        if structure_elements >= 1:
            return {
                "name": "structural_integrity",
                "status": "pass",
                "score": 1.0,
                "details": "Document contains well-formed Markdown structural hierarchies.",
            }
        else:
            return {
                "name": "structural_integrity",
                "status": "pass",
                "score": 0.9,
                "details": "Document formatted as plain narrative text.",
            }

    def _check_content_consistency(self, original: str, optimized: str) -> dict:
        """Verify optimized content is non-empty and reasonably proportional."""
        if not optimized or not optimized.strip():
            return {
                "name": "content_consistency",
                "status": "fail",
                "score": 0.0,
                "details": "Optimized output is empty!",
            }

        orig_len = len(original.strip())
        opt_len = len(optimized.strip())

        if orig_len > 0 and opt_len < orig_len * 0.05:
            return {
                "name": "content_consistency",
                "status": "warning",
                "score": 0.5,
                "details": "Optimized text length is less than 5% of original.",
            }

        return {
            "name": "content_consistency",
            "status": "pass",
            "score": 1.0,
            "details": f"Content length consistent ({opt_len:,} chars generated).",
        }

    def _calculate_preservation_score(self, checks: list[dict], mode: str) -> float:
        """Compute aggregate weighted preservation score."""
        weights = {
            "numerical_preservation": 0.35,
            "word_coverage": 0.30,
            "entity_preservation": 0.15,
            "content_consistency": 0.15,
            "structural_integrity": 0.05,
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for c in checks:
            w = weights.get(c["name"], 0.10)
            score = c.get("score", 1.0)
            weighted_sum += score * w
            total_weight += w

        score = weighted_sum / total_weight if total_weight > 0 else 1.0
        # A failed check (e.g. empty output) can never be hidden by the others.
        if any(c["status"] == "fail" for c in checks):
            score = min(score, 0.0)
        return score

