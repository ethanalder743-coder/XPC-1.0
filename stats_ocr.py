import re
import threading

import cv2
import numpy as np
from rapidocr import RapidOCR


_engine = None
_engine_lock = threading.Lock()


def _ocr_engine() -> RapidOCR:
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


def _result_lines(result) -> list[str]:
    """Support both current RapidOCR output objects and older tuple output."""
    if hasattr(result, "txts"):
        return [str(value) for value in (result.txts or []) if value]
    payload = result[0] if isinstance(result, tuple) and result else result
    if isinstance(payload, list):
        lines = []
        for item in payload:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                lines.append(str(item[1]))
            elif isinstance(item, str):
                lines.append(item)
        return lines
    return []


def _rating_from_text(text: str, rating_name: str) -> float | None:
    compact = re.sub(r"\s+", " ", text)
    names = [rating_name]
    if rating_name.casefold() == "goalkeeper":
        names.append("Goalkeeping")
    for name in names:
        escaped = re.escape(name)
        patterns = (
            rf"{escaped}\s*Rating\s*[:\-]?\s*(\d{{1,2}}(?:[.,]\d)?)",
            rf"{escaped}\s*[:\-]?\s*(\d{{1,2}}(?:[.,]\d)?)",
        )
        for pattern in patterns:
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if not match:
                continue
            raw = match.group(1).replace(",", ".")
            value = float(raw)
            if 0 <= value <= 10:
                return value
            if "." not in raw and 10 < value < 100:
                corrected = value / 10
                if corrected <= 10:
                    return corrected
    return None


def extract_rating(image_bytes: bytes, rating_name: str) -> float:
    """Read a named FC player-performance rating from a screenshot."""
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The uploaded image could not be opened. Use a PNG or JPG screenshot.")

    height, width = image.shape[:2]
    if width > 2560:
        scale = 2560 / width
        image = cv2.resize(image, (2560, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)

    variants = [image]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    variants.append(enhanced)

    all_lines: list[str] = []
    with _engine_lock:
        engine = _ocr_engine()
        for variant in variants:
            lines = _result_lines(engine(variant))
            all_lines.extend(lines)
            value = _rating_from_text("\n".join(lines), rating_name)
            if value is not None:
                return value

    if not all_lines:
        raise ValueError(
            "No text could be read from that screenshot. Upload the original full-resolution game screenshot."
        )
    raise ValueError(
        f"Could not find the {rating_name} Rating. Make sure the correct tab and its rating are clearly visible."
    )

