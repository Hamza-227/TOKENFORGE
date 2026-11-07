"""
TOKENFORGE — Token Counting Engine
====================================
Counts tokens using tiktoken (OpenAI's tokenizer).
Falls back to a word-based approximation when tiktoken is not installed.
"""

import logging
from pathlib import Path

from config import DEFAULT_ENCODING, CHUNK_SIZE

logger = logging.getLogger(__name__)

# ── Graceful tiktoken import ─────────────────────────────────────────────────
_TIKTOKEN_AVAILABLE = False
try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None
    logger.warning(
        "tiktoken is not installed — token counts will use word-based "
        "approximation (words × 1.3). Install tiktoken for accurate counts."
    )

# ── Word-based fallback multiplier ───────────────────────────────────────────
_WORD_TOKEN_RATIO = 1.3
import re as _re
_TOKEN_RE = _re.compile(r"\d+|[^\W\d]+|\n+|[^\w\s]")


class TokenCounter:
    """Counts tokens in text using tiktoken or a word-based fallback."""

    def __init__(self, encoding_name: str | None = None):
        """
        Initialise the token counter.

        Args:
            encoding_name: tiktoken encoding name (e.g. 'cl100k_base').
                           Defaults to DEFAULT_ENCODING from config.
        """
        self._encoding_name = encoding_name or DEFAULT_ENCODING
        self._encoder = None
        self._using_fallback = not _TIKTOKEN_AVAILABLE

        if _TIKTOKEN_AVAILABLE:
            try:
                self._encoder = tiktoken.get_encoding(self._encoding_name)
            except Exception as exc:
                logger.warning(
                    "Failed to load tiktoken encoding '%s': %s. "
                    "Falling back to word-based estimation.",
                    self._encoding_name,
                    exc,
                )
                self._using_fallback = True
        else:
            self._using_fallback = True

    # ── Public API ───────────────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in *text*.

        Returns:
            Integer token count (exact with tiktoken, approximate without).
        """
        if not text:
            return 0

        if self._encoder is not None and not self._using_fallback:
            try:
                return len(self._encoder.encode(text))
            except Exception as exc:
                logger.warning("tiktoken encode failed: %s — using fallback", exc)

        # Fallback: word count × 1.3
        return self._word_estimate(text)

    # Alias for convenience
    count = count_tokens

    def count_tokens_file(self, filepath) -> int:
        """
        Count tokens in a text file.

        Args:
            filepath: Path-like or string path to a UTF-8 text file.

        Returns:
            Integer token count for the entire file.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        if not filepath.is_file():
            raise ValueError(f"Not a file: {filepath}")

        total = 0
        try:
            # Read in chunks to handle large files without excessive memory use.
            # For tiktoken we accumulate the full text because sub-string
            # boundaries can split multi-byte tokens.  For the word fallback
            # counting per-chunk is safe (we just add up word counts).
            if not self._using_fallback and self._encoder is not None:
                text = filepath.read_text(encoding="utf-8", errors="replace")
                total = self.count_tokens(text)
            else:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    while True:
                        chunk = fh.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        total += self._word_estimate(chunk)
        except Exception as exc:
            logger.error("Error counting tokens in %s: %s", filepath, exc)
            raise

        return total

    def compare_representations(self, representations: dict[str, str]) -> dict:
        """
        Compare token counts across multiple text representations.

        Args:
            representations: Mapping of ``{format_name: text_content}``.

        Returns:
            Dict with each format name mapped to its token count and a
            ``'_sorted'`` key listing formats by ascending count.

        Example return::

            {
                'markdown': {'tokens': 120, 'formatted': '120 tokens'},
                'plaintext': {'tokens': 95, 'formatted': '95 tokens'},
                '_sorted': [
                    ('plaintext', 95),
                    ('markdown', 120),
                ],
            }
        """
        results: dict = {}
        for name, text in representations.items():
            count = self.count_tokens(text)
            results[name] = {
                "tokens": count,
                "formatted": format_token_count(count),
            }

        # Sorted list (ascending token count)
        sorted_list = sorted(
            [(name, info["tokens"]) for name, info in results.items()],
            key=lambda pair: pair[1],
        )
        results["_sorted"] = sorted_list
        return results

    @property
    def backend(self) -> str:
        """Human-readable name of the active counting backend."""
        return "estimate" if self._using_fallback else self._encoding_name

    @property
    def is_exact(self) -> bool:
        """True when real tiktoken counts are being used."""
        return not self._using_fallback

    def get_encoding_name(self) -> str:
        """Return the name of the encoding in use."""
        if self._using_fallback:
            return f"{self._encoding_name} (fallback: word-estimate)"
        return self._encoding_name

    def estimate_cost_savings(
        self, original_tokens: int, optimized_tokens: int
    ) -> dict:
        """
        Estimate the token savings between original and optimised content.

        Args:
            original_tokens: Token count before optimisation.
            optimized_tokens: Token count after optimisation.

        Returns:
            Dict with ``tokens_saved``, ``reduction_percentage``, and
            human-readable formatted strings.
        """
        tokens_saved = max(original_tokens - optimized_tokens, 0)

        if original_tokens > 0:
            reduction_pct = (tokens_saved / original_tokens) * 100
        else:
            reduction_pct = 0.0

        return {
            "original_tokens": original_tokens,
            "optimized_tokens": optimized_tokens,
            "tokens_saved": tokens_saved,
            "reduction_percentage": round(reduction_pct, 2),
            "original_formatted": format_token_count(original_tokens),
            "optimized_formatted": format_token_count(optimized_tokens),
            "saved_formatted": format_token_count(tokens_saved),
            "summary": (
                f"Saved {format_token_count(tokens_saved)} "
                f"({reduction_pct:.1f}% reduction)"
            ),
        }

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _word_estimate(text: str) -> int:
        """
        Offline approximation of a BPE tokenizer (used only when tiktoken
        or its vocabulary file is unavailable).

        Words cost ~1 token per 4 letters, digit runs ~1 token per 3 digits,
        each punctuation mark ~1 token and each line break ~1 token.  This is
        far closer to real tokenizer behaviour than a plain word count and,
        importantly, treats markdown/CSV punctuation fairly.
        """
        total = 0
        for m in _TOKEN_RE.finditer(text):
            piece = m.group(0)
            if piece[0].isdigit():
                total += -(-len(piece) // 3)
            elif piece[0].isalpha() or piece[0] == "_":
                total += -(-len(piece) // 4)
            elif piece[0] == "\n":
                total += 1
            else:
                total += 1
        return total


# ── Standalone convenience functions ─────────────────────────────────────────

# Module-level default counter (lazy-initialised)
_default_counter: TokenCounter | None = None


def _get_default_counter() -> TokenCounter:
    """Return (and lazily create) a module-level default TokenCounter."""
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter()
    return _default_counter


def quick_token_count(text: str) -> int:
    """
    Convenience function: count tokens in *text* using the default encoding.

    Args:
        text: Input text string.

    Returns:
        Integer token count.
    """
    return _get_default_counter().count_tokens(text)


def format_token_count(count: int) -> str:
    """
    Format a token count for human-friendly display.

    Examples:
        - 42       → ``'42 tokens'``
        - 1_234    → ``'1,234 tokens'``
        - 12_345   → ``'12.3K tokens'``
        - 1_234_567 → ``'1.2M tokens'``

    Args:
        count: Non-negative token count.

    Returns:
        Formatted string.
    """
    if count < 0:
        count = 0

    if count < 10_000:
        return f"{count:,} tokens"
    elif count < 1_000_000:
        return f"{count / 1_000:.1f}K tokens"
    else:
        return f"{count / 1_000_000:.1f}M tokens"
