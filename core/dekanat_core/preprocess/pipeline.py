"""Предобработка снимков: перспектива, тени, блики, наклон, апскейл.

Картинку оставляем цветной, цвет нужен для подписи и печати.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..settings import get_settings
from . import quality as q


@dataclass
class PreprocessResult:
    rgb: np.ndarray
    gray_for_ocr: np.ndarray
    matrix: np.ndarray               # исходные координаты -> нормализованные
    steps: list[str] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    scale: float = 1.0


def _limit_size(rgb: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return rgb, 1.0
    k = max_side / s
    return cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA), k


def _scale_matrix(k: float) -> np.ndarray:
    return np.array([[k, 0, 0], [0, k, 0], [0, 0, 1]], dtype=np.float64)


# ---------- перспектива (лист на столе) ----------
def _order_quad(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _quad_is_page(quad: np.ndarray, h: int, w: int) -> bool:
    """Проверка, что четырёхугольник похож на лист."""
    tl, tr, br, bl = _order_quad(quad)
    top, bottom = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
    left, right = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
    if min(top, bottom, left, right) < 0.25 * min(h, w):
        return False
    if min(top, bottom) / max(top, bottom) < 0.7 or min(left, right) / max(left, right) < 0.7:
        return False
    aspect = max(top, bottom) / max(left, right)
    if not (0.45 < aspect < 2.2):
        return False
    area = cv2.contourArea(quad.astype(np.float32))
    return 0.3 * h * w <= area <= 0.97 * h * w


def _largest_quad(mask: np.ndarray, h: int, w: int) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(cnt) < 0.3 * h * w:
            break
        peri = cv2.arcLength(cnt, True)
        for eps in (0.02, 0.04, 0.06):
            approx = cv2.approxPolyDP(cnt, eps * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
                if _quad_is_page(quad, h, w):
                    return quad
        hull = cv2.convexHull(cnt)
        approx = cv2.approxPolyDP(hull, 0.04 * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            if _quad_is_page(quad, h, w):
                return quad
    return None


def _paper_score(gray: np.ndarray, quad: np.ndarray) -> float:
    """Яркость внутри минус яркость снаружи."""
    h, w = gray.shape
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [quad.astype(np.int32)], 255)
    inside = float(gray[mask > 0].mean())
    outside_px = gray[mask == 0]
    if outside_px.size < 0.03 * h * w:
        return inside - 128  # лист почти на весь кадр, смотрим только яркость
    return inside - float(outside_px.mean())


def find_page_quad(rgb: np.ndarray) -> np.ndarray | None:
    """Ищет контур листа, берём самый маленький подходящий вариант."""
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    candidates: list[np.ndarray] = []

    edges = cv2.Canny(blur, 30, 90)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        filled = edges.copy()
        ff = np.zeros((h + 2, w + 2), np.uint8)
        cv2.floodFill(filled, ff, seed, 255)
        filled = cv2.bitwise_or(edges, cv2.bitwise_not(filled))
        quad = _largest_quad(filled, h, w)
        if quad is not None:
            candidates.append(quad)
    for src in (blur, cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(blur)):
        _, th = cv2.threshold(src, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))
        quad = _largest_quad(th, h, w)
        if quad is not None:
            candidates.append(quad)

    valid = [(cv2.contourArea(c.astype(np.float32)), c) for c in candidates if _paper_score(gray, c) > 25]
    if not valid:
        return None
    valid.sort(key=lambda t: t[0])
    return valid[0][1]


def warp_perspective(rgb: np.ndarray, quad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tl, tr, br, bl = _order_quad(quad)
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if w < 100 or h < 100:
        return rgb, np.eye(3)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), dst)
    return cv2.warpPerspective(rgb, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)), M


# ---------- наклон ----------
def estimate_skew(gray: np.ndarray, max_angle: float) -> float:
    """Угол наклона строк в градусах."""
    small = gray
    if max(gray.shape) > 1500:
        k = 1500 / max(gray.shape)
        small = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    th = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    edges = cv2.Canny(th, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=80, minLineLength=small.shape[1] // 6, maxLineGap=20)
    if lines is None:
        return 0.0
    angles, weights = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) <= max_angle:
            angles.append(ang)
            weights.append(np.hypot(x2 - x1, y2 - y1))
    if not angles:
        return 0.0
    angles, weights = np.array(angles), np.array(weights)
    order = np.argsort(angles)
    cum = np.cumsum(weights[order])
    return float(angles[order][np.searchsorted(cum, cum[-1] / 2)])


def rotate_keep(rgb: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    h, w = rgb.shape[:2]
    c = (w / 2, h / 2)
    R = cv2.getRotationMatrix2D(c, angle, 1.0)
    cos, sin = abs(R[0, 0]), abs(R[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    R[0, 2] += nw / 2 - c[0]
    R[1, 2] += nh / 2 - c[1]
    out = cv2.warpAffine(rgb, R, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return out, np.vstack([R, [0, 0, 1]])


# ---------- тени / блики ----------
def remove_shadow(rgb: np.ndarray) -> np.ndarray:
    """Делим на фон, чтобы выровнять освещение."""
    out = []
    for ch in cv2.split(rgb):
        bg = cv2.medianBlur(cv2.dilate(ch, np.ones((9, 9), np.uint8)), 51)
        bg = np.maximum(bg, 1).astype(np.float32)
        norm = np.clip(ch.astype(np.float32) / bg * 245.0, 0, 255).astype(np.uint8)
        out.append(norm)
    return cv2.merge(out)


def soften_glare(rgb: np.ndarray) -> tuple[np.ndarray, bool]:
    """Приглушает блики до уровня бумаги."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    v, s = hsv[:, :, 2], hsv[:, :, 1]
    paper = np.median(v[v > 150]) if (v > 150).any() else 255
    if paper >= 252:
        return rgb, False
    mask = ((v > min(254, paper + 15)) & (s < 25)).astype(np.uint8)
    if mask.mean() < 0.003:
        return rgb, False
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    out = rgb.copy()
    out[mask.astype(bool)] = np.clip(rgb[mask.astype(bool)].astype(np.int32) - int(255 - paper), 0, 255).astype(np.uint8)
    return out, True


# ---------- шум / муар ----------
def noise_ratio(rgb: np.ndarray) -> float:
    """Доля тёмных пикселей после адаптивного порога (чистый лист 0.01-0.03, муар > 0.05)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if max(gray.shape) > 1600:
        k = 1600 / max(gray.shape)
        gray = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    return float(th.mean() / 255)


# ---------- высота текста ----------
def estimate_text_height(gray: np.ndarray) -> float:
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    hs = stats[1:, cv2.CC_STAT_HEIGHT]
    ws = stats[1:, cv2.CC_STAT_WIDTH]
    ok = (hs > 4) & (hs < gray.shape[0] * 0.05) & (ws < gray.shape[1] * 0.2)
    if ok.sum() < 20:
        return 0.0
    return float(np.median(hs[ok]))


def gray_for_ocr(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def run(rgb: np.ndarray) -> PreprocessResult:
    cfg = get_settings().get("preprocess", {})
    steps: list[str] = []
    M = np.eye(3)
    rgb, k = _limit_size(rgb, cfg.get("max_side", 2400))
    if k != 1.0:
        M = _scale_matrix(k) @ M
        steps.append(f"resize x{k:.2f}")

    # фото с телефона часто бывают повёрнуты
    if cfg.get("enable_orientation", True):
        from .orientation import fix_orientation

        rgb, Mo, angle, src = fix_orientation(rgb, cfg.get("orientation_min_conf", 0.6))
        if angle:
            M = Mo @ M
            steps.append(f"orientation {angle}° ({src})")
    quality = q.assess(rgb)

    if not quality["is_scan_like"]:
        if cfg.get("enable_perspective", True):
            quad = find_page_quad(rgb)
            if quad is not None:
                rgb, Mp = warp_perspective(rgb, quad)
                M = Mp @ M
                steps.append("perspective")
        if cfg.get("enable_shadow_removal", True) and quality["bg_unevenness"] > 20:
            rgb = remove_shadow(rgb)
            steps.append("shadow")
        if cfg.get("enable_glare_removal", True):
            rgb, done = soften_glare(rgb)
            if done:
                steps.append("glare")

    # муар и шум (фото экрана), без этого детектор печати находит кольца в шуме
    noise = noise_ratio(rgb)
    quality["noise_ratio"] = round(noise, 4)
    if cfg.get("enable_denoise", True) and noise > cfg.get("denoise_noise_threshold", 0.05):
        rgb = cv2.bilateralFilter(rgb, 7, 60, 60)
        steps.append(f"denoise (noise {noise:.2f})")

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    angle = estimate_skew(gray, cfg.get("deskew_max_angle", 30))
    if abs(angle) > 0.3:
        rgb, Mr = rotate_keep(rgb, angle)
        M = Mr @ M
        steps.append(f"deskew {angle:.1f}°")
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    th = estimate_text_height(gray)
    scale = 1.0
    if 0 < th < cfg.get("min_text_height_px", 18):
        scale = 2.0
        rgb = cv2.resize(rgb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        M = _scale_matrix(2.0) @ M
        steps.append("upscale x2")

    return PreprocessResult(rgb=rgb, gray_for_ocr=gray_for_ocr(rgb), matrix=M, steps=steps, quality=quality, scale=scale)


def map_bbox_back(bbox, M: np.ndarray):
    """Переводит bbox обратно в координаты исходного снимка."""
    x1, y1, x2, y2 = bbox
    pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float64)
    Minv = np.linalg.inv(M)
    hom = np.hstack([pts, np.ones((4, 1))]) @ Minv.T
    hom /= hom[:, 2:3]
    return [[float(x), float(y)] for x, y in hom[:, :2]]
