"""Оценка качества снимка, от неё зависят шаги предобработки."""
from __future__ import annotations

import cv2
import numpy as np


def assess(rgb: np.ndarray) -> dict:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean = float(gray.mean())
    std = float(gray.std())
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    glare_ratio = float(((hsv[:, :, 2] > 245) & (hsv[:, :, 1] < 25)).mean())
    # неравномерность освещения
    small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
    bg_unevenness = float(np.percentile(small, 90) - np.percentile(small, 10))
    # доля светлых пикселей, у сканов около 0.9, у фото меньше
    paper_ratio = float((gray > 180).mean())
    return {
        "width": int(w),
        "height": int(h),
        "sharpness": round(lap_var, 1),
        "brightness": round(mean, 1),
        "contrast": round(std, 1),
        "glare_ratio": round(glare_ratio, 4),
        "bg_unevenness": round(bg_unevenness, 1),
        "paper_ratio": round(paper_ratio, 3),
        "is_scan_like": bool(paper_ratio > 0.85 and bg_unevenness < 25),
        "low_resolution": bool(max(h, w) < 1000),
    }
