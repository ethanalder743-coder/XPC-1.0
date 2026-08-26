import re

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


_engine = None


def _ocr_engine() -> RapidOCR:
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


def extract_rating(image_bytes: bytes, rating_name: str) -> float:
    """Read a named FC player-performance rating from a screenshot."""
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The uploaded image could not be opened.")
    results, _ = _ocr_engine()(image)
    if not results:
        raise ValueError("No text could be read from the screenshot.")
    lines = [str(item[1]) for item in results]
    text = "\n".join(lines)
    compact = re.sub(r"\s+", " ", text)
    escaped = re.escape(rating_name)
    patterns = [
        rf"{escaped}\s*Rating\s*[:\-]?\s*(\d{{1,2}}(?:[.,]\d)?)",
        rf"{escaped}\s*[:\-]?\s*(\d{{1,2}}(?:[.,]\d)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1).replace(",", "."))
            if 0 <= value <= 10:
                return value
    raise ValueError(
        f"Could not find the {rating_name} Rating. Make sure that tab and rating are visible."
    )

