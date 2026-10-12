"""PaddleOCR через модели paddlex напрямую (детектор + кириллическая модель распознавания).

Класс PaddleOCR не используем, т.к. на Windows детектору нужен run_mode=paddle.
"""
from __future__ import annotations

import logging
import os
import threading

import cv2
import numpy as np

from ..models import OcrLine
from ..settings import get_settings
from .base import OcrEngine

log = logging.getLogger(__name__)
_lock = threading.Lock()

DET_MODEL = os.environ.get("DEKANAT_PADDLE_DET", "PP-OCRv5_mobile_det")
REC_MODEL = os.environ.get("DEKANAT_PADDLE_REC", "eslav_PP-OCRv5_mobile_rec")


def _order_points(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def crop_poly(img: np.ndarray, poly) -> np.ndarray:
    """Вырезает строку текста по четырёхугольнику."""
    pts = np.array(poly, dtype=np.float32).reshape(-1, 2)
    if len(pts) != 4:
        x1, y1 = pts.min(axis=0)
        x2, y2 = pts.max(axis=0)
        return img[int(y1):int(y2) + 1, int(x1):int(x2) + 1]
    tl, tr, br, bl = _order_points(pts)
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    w, h = max(w, 4), max(h, 4)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), dst)
    crop = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if h > 1.5 * w:  # вертикальная строка
        crop = np.rot90(crop)
    return crop


class PaddleEngine(OcrEngine):
    name = "paddle"

    def __init__(self):
        self._det = None
        self._rec = None
        self._failed = False

    def _load(self):
        if (self._det is not None and self._rec is not None) or self._failed:
            return
        with _lock:
            if (self._det is not None and self._rec is not None) or self._failed:
                return
            cfg = get_settings().get("ocr", {})
            threads = int(cfg.get("cpu_threads", 8))
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            try:
                from paddlex import create_model  # type: ignore

                device = "gpu" if cfg.get("use_gpu") else "cpu"
                det_engine = {"cpu_threads": threads}
                if device == "cpu":
                    # на Windows детектор падает с oneDNN + PIR
                    det_engine.update(run_mode="paddle", enable_new_ir=False)
                self._det = create_model(model_name=cfg.get("paddle_det_model", DET_MODEL), device=device,
                                         engine_config=det_engine)
                self._rec = create_model(model_name=cfg.get("paddle_rec_model", REC_MODEL), device=device,
                                         engine_config={"cpu_threads": threads})
                log.info("PaddleOCR загружен: %s + %s", DET_MODEL, REC_MODEL)
            except Exception as exc:  # pragma: no cover
                log.warning("PaddleOCR недоступен: %s", exc)
                self._failed = True

    def available(self) -> bool:
        self._load()
        return self._det is not None and self._rec is not None

    @staticmethod
    def _res(r) -> dict:
        return r if isinstance(r, dict) else r.json["res"]

    def recognize(self, rgb: np.ndarray) -> list[OcrLine]:
        self._load()
        if self._det is None or self._rec is None:
            return []
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        with _lock:
            det_out = list(self._det.predict(bgr))
            polys = self._res(det_out[0]).get("dt_polys", []) if det_out else []
            if len(polys) == 0:
                return []
            crops = [crop_poly(bgr, p) for p in polys]
            rec_out = list(self._rec.predict(crops, batch_size=16))
        lines: list[OcrLine] = []
        for poly, r in zip(polys, rec_out):
            d = self._res(r)
            text = str(d.get("rec_text", "")).strip()
            if not text:
                continue
            pts = np.array(poly).reshape(-1, 2)
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            lines.append(OcrLine(text=text, bbox=(int(x1), int(y1), int(x2), int(y2)),
                                 conf=float(d.get("rec_score", 0.0)), engine=self.name))
        return lines
