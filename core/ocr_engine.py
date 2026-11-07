"""
TOKENFORGE — OCR Engine
========================
Extracts text from images using Tesseract OCR via pytesseract.
Uses OpenCV (cv2) for image preprocessing to improve OCR quality.
Gracefully handles the case where Tesseract is not installed.
"""

import logging
import warnings
from pathlib import Path

from config import TESSERACT_LANG, OCR_CONFIDENCE_THRESHOLD, OCR_DPI

logger = logging.getLogger(__name__)

# ── Graceful optional-dependency imports ─────────────────────────────────────
_TESSERACT_AVAILABLE = False
_CV2_AVAILABLE = False
_PIL_AVAILABLE = False

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None  # type: ignore[assignment]
    logger.warning("pytesseract is not installed — OCR will be unavailable.")

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None   # type: ignore[assignment]
    logger.warning(
        "opencv-python (cv2) is not installed — image preprocessing "
        "will be skipped."
    )

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    PILImage = None  # type: ignore[assignment]
    logger.warning("Pillow (PIL) is not installed — image handling limited.")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_pil_image(image_path_or_pil_image) -> "PILImage.Image":
    """
    Accept a file path (str / Path) or an existing PIL Image and return
    a PIL Image instance.

    Raises:
        RuntimeError: If Pillow is not installed.
        FileNotFoundError: If the path does not exist.
    """
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for image handling but is not installed.")

    if isinstance(image_path_or_pil_image, PILImage.Image):
        return image_path_or_pil_image

    path = Path(image_path_or_pil_image)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    return PILImage.open(path)


def _pil_to_cv2(pil_image: "PILImage.Image"):
    """Convert a PIL Image to an OpenCV (numpy) BGR array."""
    if not _CV2_AVAILABLE:
        raise RuntimeError("OpenCV is required for this operation but is not installed.")
    # Ensure RGB mode for consistent conversion
    rgb = pil_image.convert("RGB")
    arr = np.array(rgb)
    # PIL is RGB, cv2 uses BGR
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _cv2_to_pil(cv2_image) -> "PILImage.Image":
    """Convert an OpenCV BGR array to a PIL Image."""
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for this operation but is not installed.")
    rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
    return PILImage.fromarray(rgb)


def _empty_result(warning_msg: str = "") -> dict:
    """Return an empty OCR result dict, optionally with a warning."""
    result = {
        "text": "",
        "confidence": 0.0,
        "language": "",
        "word_count": 0,
    }
    if warning_msg:
        result["warning"] = warning_msg
        logger.warning(warning_msg)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  OCREngine
# ══════════════════════════════════════════════════════════════════════════════

class OCREngine:
    """
    Extracts text from images using Tesseract OCR.

    Falls back gracefully when Tesseract or its Python bindings are absent —
    methods return empty results with descriptive warnings instead of raising.
    """

    def __init__(self):
        """Initialise the OCR engine and probe for Tesseract availability."""
        self._lang = TESSERACT_LANG
        self._confidence_threshold = OCR_CONFIDENCE_THRESHOLD
        self._dpi = OCR_DPI
        self.available = False

        if not _TESSERACT_AVAILABLE:
            logger.info("OCREngine: pytesseract not installed — OCR disabled.")
            return

        # Smart discovery for Tesseract executable (especially on Windows & Conda)
        import sys
        import shutil
        candidate_paths = [
            Path(sys.prefix) / "Library" / "bin" / "tesseract.exe",
            Path(sys.prefix) / "Scripts" / "tesseract.exe",
            Path(sys.prefix) / "bin" / "tesseract",
            Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
            Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
        ]
        for candidate in candidate_paths:
            if candidate.exists():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                break
        else:
            found_which = shutil.which("tesseract")
            if found_which:
                pytesseract.pytesseract.tesseract_cmd = found_which

        # Verify that the tesseract binary is reachable
        try:
            pytesseract.get_tesseract_version()
            self.available = True
            logger.info("OCREngine: Tesseract is available.")
        except Exception as exc:
            logger.warning(
                "OCREngine: Tesseract binary not found or not working: %s. "
                "OCR will be unavailable.",
                exc,
            )
            self.available = False

    # ── Public API ───────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return whether Tesseract OCR is operational."""
        return self.available

    def extract_text_from_image(self, image_path_or_pil_image) -> dict:
        """
        Extract text from a single image.

        Args:
            image_path_or_pil_image: A file path (str/Path) or a PIL Image.

        Returns:
            Dict with keys ``text``, ``confidence``, ``language``,
            ``word_count``, and optionally ``warning``.
        """
        if not self.available:
            return _empty_result("OCR is not available (Tesseract not found).")

        try:
            pil_image = _load_pil_image(image_path_or_pil_image)
        except Exception as exc:
            return _empty_result(f"Failed to load image: {exc}")

        # Preprocess for better accuracy
        try:
            preprocessed = self.preprocess_image(pil_image)
        except Exception:
            preprocessed = pil_image

        # Run OCR with detailed output to get per-word confidence
        try:
            data = pytesseract.image_to_data(
                preprocessed,
                lang=self._lang,
                config=f"--dpi {self._dpi}",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            return _empty_result(f"Tesseract OCR failed: {exc}")

        # Aggregate results, filtering by confidence threshold
        words: list[str] = []
        confidences: list[float] = []

        for i, word in enumerate(data.get("text", [])):
            word = word.strip()
            if not word:
                continue
            conf = float(data["conf"][i])
            if conf < 0:
                # pytesseract returns -1 for empty/header rows
                continue
            if conf >= self._confidence_threshold:
                words.append(word)
                confidences.append(conf)

        text = " ".join(words)
        avg_confidence = (
            round(sum(confidences) / len(confidences), 2)
            if confidences
            else 0.0
        )

        return {
            "text": text,
            "confidence": avg_confidence,
            "language": self._lang,
            "word_count": len(words),
        }

    def extract_text(self, image_path_or_pil_image) -> dict:
        """Alias for :meth:`extract_text_from_image` (used by processors)."""
        return self.extract_text_from_image(image_path_or_pil_image)

    def ocr_image_bytes(self, image_bytes: bytes) -> str:
        """OCR raw encoded image bytes (PNG/JPEG...) and return plain text."""
        if not self.available:
            return ""
        import io
        pil = PILImage.open(io.BytesIO(image_bytes))
        return self.extract_text_from_image(pil).get("text", "")

    def extract_text_with_layout(self, image_path_or_pil_image) -> str:
        """
        Extract text while preserving spatial layout (line/block positions).

        Args:
            image_path_or_pil_image: A file path (str/Path) or a PIL Image.

        Returns:
            Text string with layout preserved via whitespace/newlines.
            Returns an empty string if OCR is unavailable.
        """
        if not self.available:
            warnings.warn("OCR is not available — returning empty text.")
            return ""

        try:
            pil_image = _load_pil_image(image_path_or_pil_image)
        except Exception as exc:
            logger.error("Failed to load image for layout OCR: %s", exc)
            return ""

        try:
            preprocessed = self.preprocess_image(pil_image)
        except Exception:
            preprocessed = pil_image

        try:
            # Tesseract's --psm 6 treats the image as a uniform block of text
            layout_text = pytesseract.image_to_string(
                preprocessed,
                lang=self._lang,
                config=f"--dpi {self._dpi} --psm 6",
            )
            return layout_text
        except Exception as exc:
            logger.error("Layout OCR failed: %s", exc)
            return ""

    def preprocess_image(self, image) -> "PILImage.Image":
        """
        Preprocess a PIL Image for higher-quality OCR.

        Steps:
            1. Convert to grayscale.
            2. Apply adaptive thresholding (binarisation).
            3. Denoise with a median blur.

        If OpenCV is not available the original image is returned as-is.

        Args:
            image: A PIL Image.

        Returns:
            Preprocessed PIL Image.
        """
        if not _PIL_AVAILABLE:
            raise RuntimeError("Pillow is required for preprocessing.")

        pil_image = _load_pil_image(image)

        if not _CV2_AVAILABLE:
            # Best-effort: at least convert to grayscale via Pillow
            return pil_image.convert("L")

        try:
            cv_img = _pil_to_cv2(pil_image)

            # 1. Grayscale
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

            # 2. Denoise (median blur removes salt-and-pepper noise)
            denoised = cv2.medianBlur(gray, 3)

            # 3. Adaptive threshold for binarisation
            binary = cv2.adaptiveThreshold(
                denoised,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                blockSize=31,
                C=11,
            )

            # Convert back to PIL
            return PILImage.fromarray(binary)

        except Exception as exc:
            logger.warning(
                "Image preprocessing with OpenCV failed: %s. "
                "Returning grayscale fallback.",
                exc,
            )
            return pil_image.convert("L")

    def detect_text_regions(self, image) -> list[dict]:
        """
        Detect rectangular regions in the image that contain text.

        Args:
            image: A file path (str/Path) or PIL Image.

        Returns:
            List of dicts, each with:
                - ``bbox``: ``(x, y, width, height)``
                - ``confidence``: Average confidence for that region.
                - ``text``: Detected text in the region.
        """
        if not self.available:
            logger.warning("OCR not available — cannot detect text regions.")
            return []

        try:
            pil_image = _load_pil_image(image)
        except Exception as exc:
            logger.error("Failed to load image for region detection: %s", exc)
            return []

        try:
            preprocessed = self.preprocess_image(pil_image)
        except Exception:
            preprocessed = pil_image

        try:
            data = pytesseract.image_to_data(
                preprocessed,
                lang=self._lang,
                config=f"--dpi {self._dpi}",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            logger.error("Tesseract region detection failed: %s", exc)
            return []

        # Group words into blocks (Tesseract assigns block_num)
        blocks: dict[int, list[int]] = {}
        for i, text in enumerate(data.get("text", [])):
            text = text.strip()
            if not text:
                continue
            conf = float(data["conf"][i])
            if conf < 0:
                continue
            block_num = data["block_num"][i]
            blocks.setdefault(block_num, []).append(i)

        regions: list[dict] = []
        for _block_num, indices in blocks.items():
            xs = [data["left"][i] for i in indices]
            ys = [data["top"][i] for i in indices]
            x_ends = [data["left"][i] + data["width"][i] for i in indices]
            y_ends = [data["top"][i] + data["height"][i] for i in indices]
            confs = [float(data["conf"][i]) for i in indices]
            words = [data["text"][i].strip() for i in indices]

            x = min(xs)
            y = min(ys)
            w = max(x_ends) - x
            h = max(y_ends) - y
            avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0

            if avg_conf >= self._confidence_threshold:
                regions.append({
                    "bbox": (x, y, w, h),
                    "confidence": avg_conf,
                    "text": " ".join(words),
                })

        return regions

    def is_scanned_page(self, image) -> bool:
        """
        Heuristic: decide whether an image looks like a scanned document page
        (as opposed to a photograph or diagram).

        Heuristics used:
            - Predominantly white/light background.
            - High text-region coverage.
            - Low colour saturation.

        Args:
            image: A file path (str/Path) or PIL Image.

        Returns:
            ``True`` if the image appears to be a scanned page.
        """
        try:
            pil_image = _load_pil_image(image)
        except Exception as exc:
            logger.error("Failed to load image for scan detection: %s", exc)
            return False

        if not _CV2_AVAILABLE:
            # Fallback: use PIL histogram as a rough proxy
            try:
                gray = pil_image.convert("L")
                histogram = gray.histogram()
                total_pixels = sum(histogram)
                # Count pixels in the "light" range (200-255)
                light_pixels = sum(histogram[200:256])
                light_ratio = light_pixels / total_pixels if total_pixels else 0
                # Scanned pages are typically >40 % light background
                return light_ratio > 0.40
            except Exception:
                return False

        try:
            cv_img = _pil_to_cv2(pil_image)

            # 1. Check colour saturation (scanned docs are mostly desaturated)
            hsv = cv2.cvtColor(cv_img, cv2.COLOR_BGR2HSV)
            mean_saturation = float(hsv[:, :, 1].mean())

            # 2. Check brightness (scanned pages have lots of white)
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            total_pixels = gray.size
            light_pixels = int((gray > 200).sum())
            light_ratio = light_pixels / total_pixels

            # 3. Aspect ratio — scanned pages tend to be portrait or ~letter
            h, w = gray.shape[:2]
            aspect = w / h if h else 1.0
            is_page_aspect = 0.5 < aspect < 1.5  # roughly portrait/letter

            # Decision: low saturation + high light ratio + page aspect
            is_scanned = (
                mean_saturation < 60
                and light_ratio > 0.40
                and is_page_aspect
            )
            return is_scanned

        except Exception as exc:
            logger.warning("Scan-page detection failed: %s", exc)
            return False

    def batch_ocr(self, images: list) -> list[dict]:
        """
        Run OCR on multiple images.

        Args:
            images: List of file paths (str/Path) or PIL Images.

        Returns:
            List of result dicts (same structure as
            :meth:`extract_text_from_image`).
        """
        if not self.available:
            warning = "OCR is not available (Tesseract not found)."
            return [_empty_result(warning) for _ in images]

        results: list[dict] = []
        for idx, image in enumerate(images):
            try:
                result = self.extract_text_from_image(image)
            except Exception as exc:
                result = _empty_result(
                    f"OCR failed for image {idx}: {exc}"
                )
            results.append(result)

        return results
