"""Основной движок PaddleOCR, запасной Tesseract."""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from rapidfuzz import fuzz

from ..models import OcrLine
from ..settings import get_settings
from .base import OcrEngine
from .paddle_engine import PaddleEngine
from .tesseract_engine import TesseractEngine

log = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def get_engine(name: str) -> OcrEngine:
    if name == "paddle":
        return PaddleEngine()
    if name == "tesseract":
        return TesseractEngine()
    raise ValueError(f"Неизвестный OCR-движок: {name}")


def _label_hit_ratio(lines: list[OcrLine], expected_labels) -> float:
    """Доля найденных меток (для списка списков берём максимум)."""
    if not expected_labels:
        return 1.0
    if expected_labels and isinstance(expected_labels[0], (list, tuple)):
        return max(_label_hit_ratio(lines, labs) for labs in expected_labels)
    texts = [l.text.lower() for l in lines]
    hits = 0
    for lab in expected_labels:
        lab = lab.lower()
        if any(fuzz.partial_ratio(lab, t) >= 85 for t in texts):
            hits += 1
    return hits / len(expected_labels)


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    return inter / ((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)


def merge(primary: list[OcrLine], secondary: list[OcrLine]) -> list[OcrLine]:
    """Добавляет из secondary строки, которых нет в primary."""
    out = list(primary)
    for s in secondary:
        if any(_iou(s.bbox, p.bbox) > 0.3 for p in primary):
            continue
        out.append(s)
    return out


def recognize(rgb: np.ndarray, expected_labels=None) -> tuple[list[OcrLine], dict]:
    cfg = get_settings().get("ocr", {})
    primary_name = cfg.get("primary", "paddle")
    fallback_name = cfg.get("fallback", "tesseract")
    info: dict = {"engines": []}

    primary = get_engine(primary_name)
    lines: list[OcrLine] = []
    if primary.available():
        lines = primary.recognize(rgb)
        info["engines"].append(primary_name)
    mean_conf = float(np.mean([l.conf for l in lines])) if lines else 0.0
    hit = _label_hit_ratio(lines, expected_labels or [])
    info.update(primary_mean_conf=round(mean_conf, 3), label_hit_ratio=round(hit, 2))

    need_fallback = (not lines) or mean_conf < cfg.get("min_mean_conf", 0.75) or hit < cfg.get("min_label_hits", 0.6)
    if need_fallback and fallback_name and fallback_name != primary_name:
        fb = get_engine(fallback_name)
        if fb.available():
            fb_lines = fb.recognize(rgb)
            info["engines"].append(fallback_name)
            fb_hit = _label_hit_ratio(fb_lines, expected_labels or [])
            info["fallback_label_hit_ratio"] = round(fb_hit, 2)
            if not lines or fb_hit > hit + 0.15:
                lines = merge(fb_lines, lines)
                info["chosen"] = fallback_name
            else:
                lines = merge(lines, fb_lines)
                info["chosen"] = primary_name
    else:
        info["chosen"] = primary_name if lines else None
    return lines, info
