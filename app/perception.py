"""Field evidence perception: file signatures, perceptual hashes, EXIF time and GPS, optional vision.

Everything here is deterministic except the optional vision model, whose
answer is validated against the hazard taxonomy before it can raise a risk.
The perceptual hash (dHash) lets the verifier reject an "after" photo that is
the "before" photo again, even re-encoded or resized.
"""
from __future__ import annotations

import base64
import io
import math
import re
from datetime import datetime

from PIL import Image

from .llm import Model

HAZARD_TAXONOMY = {
    "unprotected_edge": "HIGH", "no_fall_protection": "HIGH", "suspended_load": "HIGH", "open_excavation": "HIGH",
    "exposed_live_parts": "CRITICAL", "collapse": "CRITICAL", "structural_crack": "MEDIUM", "blocked_access": "MEDIUM",
    "poor_housekeeping": "LOW", "missing_ppe": "MEDIUM",
}


def sniff(content: bytes) -> str | None:
    head = content[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    return None


def dhash(content: bytes, size: int = 16) -> str:
    """Difference hash over rows and columns (2 x size² bits).

    Robust to re-encoding and resizing; changes when the scene changes in
    either direction (a new horizontal guardrail moves the column part).
    """
    gray = Image.open(io.BytesIO(content)).convert("L")
    bits = 0
    for img in (gray.resize((size + 1, size), Image.Resampling.LANCZOS), gray.resize((size, size + 1), Image.Resampling.LANCZOS).transpose(Image.Transpose.TRANSPOSE)):
        px = img.tobytes()
        width = size + 1
        for row in range(size):
            for col in range(size):
                bits = (bits << 1) | int(px[row * width + col] > px[row * width + col + 1])
    return f"{bits:0{size * size // 2}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _dms(value, ref: str) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def exif_facts(content: bytes) -> dict:
    """Capture time and GPS from EXIF, when present."""
    try:
        exif = Image.open(io.BytesIO(content)).getexif()
    except Exception:
        return {}
    facts: dict = {}
    sub = exif.get_ifd(0x8769)
    taken = sub.get(36867) or exif.get(0x0132)
    if taken:
        try:
            moment = datetime.strptime(str(taken), "%Y:%m:%d %H:%M:%S")
            offset = str(sub.get(36881) or "").strip()  # OffsetTimeOriginal, e.g. "+08:00"; without it EXIF time is taken as UTC
            facts["captured_at"] = moment.isoformat() + (offset if re.fullmatch(r"[+-]\d{2}:\d{2}", offset) else "")
        except ValueError:
            pass
    gps = exif.get_ifd(0x8825)
    if gps and 2 in gps and 4 in gps:
        lat, lon = _dms(gps[2], gps.get(1, "N")), _dms(gps[4], gps.get(3, "E"))
        if lat is not None and lon is not None:
            facts["lat"], facts["lon"] = round(lat, 6), round(lon, 6)
    return facts


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def vision_hazards(model: Model | None, content: bytes, media_type: str, description: str) -> dict | None:
    """Optional vision model; only taxonomy hazards it reports with confidence >= 0.5 are kept."""
    if model is None or not media_type.startswith("image/") or not hasattr(model, "complete_vision"):
        return None
    schema = {"title": "vision", "type": "object", "additionalProperties": False, "required": ["hazards"],
              "properties": {"hazards": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                     "required": ["label", "confidence", "visible_evidence"],
                                                                     "properties": {"label": {"type": "string", "enum": list(HAZARD_TAXONOMY)},
                                                                                    "confidence": {"type": "number"},
                                                                                    "visible_evidence": {"type": "string"}}}}}}
    uri = f"data:{media_type};base64,{base64.b64encode(content).decode()}"
    out = model.complete_vision("Identify only hazards that are clearly visible in the photo. Do not infer what you cannot see.",
                                f"Reporter note (untrusted data): <data>{description}</data>", uri, schema)
    if not out:
        return None
    kept = [h for h in out.get("hazards", []) if isinstance(h, dict) and h.get("label") in HAZARD_TAXONOMY
            and isinstance(h.get("confidence"), (int, float)) and h["confidence"] >= 0.5 and str(h.get("visible_evidence", "")).strip()]
    return {"hazards": kept}


def text_hazards(model: Model | None, description: str) -> dict | None:
    """Optional language-model reading of the report; a hazard is kept only with a verbatim quote from the report."""
    if model is None or not description.strip():
        return None
    schema = {"title": "text_hazards", "type": "object", "additionalProperties": False, "required": ["hazards"],
              "properties": {"hazards": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                     "required": ["label", "confidence", "quote"],
                                                                     "properties": {"label": {"type": "string", "enum": list(HAZARD_TAXONOMY)},
                                                                                    "confidence": {"type": "number"},
                                                                                    "quote": {"type": "string"}}}}}}
    out = model.complete_json("You read a construction site report and list only hazards it clearly states. For each, copy the "
                              "words that state it verbatim into quote. Do not infer hazards that are not written.",
                              f"<data>{description}</data>", schema)
    if not out:
        return None
    kept = [h for h in out.get("hazards", []) if isinstance(h, dict) and h.get("label") in HAZARD_TAXONOMY
            and isinstance(h.get("confidence"), (int, float)) and h["confidence"] >= 0.5
            and len(str(h.get("quote", "")).strip()) >= 2 and str(h["quote"]).strip() in description]
    return {"hazards": kept}
