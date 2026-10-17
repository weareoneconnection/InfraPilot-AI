"""Synthetic site photos with EXIF time and GPS, for demos, tests and the benchmark.

A "before" scene shows a deck edge with no guardrail; the "after" scene adds a
guardrail. Images are generated, never real site photos.
"""
from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw


def _dms(value: float) -> tuple[float, float, float]:
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    return float(d), float(m), round((value - d - m / 60) * 3600, 2)


def photo(scene: str = "before", *, captured_at: datetime | None = None, lat: float | None = None, lon: float | None = None,
          variant: int = 0, quality: int = 88, size: tuple[int, int] = (640, 480)) -> bytes:
    w, h = size
    img = Image.new("RGB", (w, h), (176, 190, 201))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.55), w, h], fill=(122, 118, 110))                    # deck slab
    d.rectangle([0, int(h * 0.52), w, int(h * 0.55)], fill=(90, 86, 80))          # slab edge
    d.polygon([(int(w * 0.62), int(h * 0.55)), (w, int(h * 0.55)), (w, h)], fill=(60, 66, 74))  # drop beyond the edge
    for i in range(3 + variant % 3):                                              # workers / materials vary by variant
        x = 40 + i * 120 + variant * 7
        d.rectangle([x, int(h * 0.38), x + 26, int(h * 0.55)], fill=(220, 120 + 20 * i, 40))
    if scene == "after":
        for x in range(0, w, 48):                                                 # guardrail posts
            d.rectangle([x, int(h * 0.30), x + 8, int(h * 0.55)], fill=(250, 210, 0))
        for y in (0.33, 0.43):                                                    # top and mid rails
            d.rectangle([0, int(h * y), w, int(h * y) + 9], fill=(250, 210, 0))
    exif = Image.Exif()
    if captured_at:
        stamp = captured_at.strftime("%Y:%m:%d %H:%M:%S")
        exif[0x0132] = stamp
        exif.get_ifd(0x8769)[36867] = stamp
    if lat is not None and lon is not None:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
        gps[3], gps[4] = ("E" if lon >= 0 else "W"), _dms(lon)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, exif=exif)
    return buf.getvalue()


def reencode(content: bytes, quality: int = 55, scale: float = 0.75) -> bytes:
    """The same picture re-saved smaller: what reusing an old photo looks like."""
    img = Image.open(io.BytesIO(content))
    exif = img.getexif()
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, exif=exif)
    return buf.getvalue()
