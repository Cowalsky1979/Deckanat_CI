"""Определение ориентации страницы (0/90/180/270). Сначала PaddleX, если не вышло, то Tesseract OSD."""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from ..settings import get_settings

log = logging.getLogger(__name__)
_lock = threading.Lock()
_model = None
_model_failed = False

ORI_MODEL = os.environ.get("DEKANAT_PADDLE_ORI", "PP-LCNet_x1_0_doc_ori")


def _load_model():
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    with _lock:
        if _model is not None or _model_failed:
            return _model
        try:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddlex import create_model  # type: ignore

            threads = int(get_settings().get("ocr", {}).get("cpu_threads", 8))
            _model = create_model(model_name=ORI_MODEL, device="cpu", engine_config={"cpu_threads": threads})
            log.info("Классификатор ориентации %s загружен", ORI_MODEL)
        except Exception as exc:  # pragma: no cover
            log.warning("Классификатор ориентации недоступен: %s", exc)
            _model_failed = True
    return _model


def _detect_paddle(rgb: np.ndarray) -> tuple[int, float] | None:
    m = _load_model()
    if m is None:
        return None
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    with _lock:
        out = list(m.predict(bgr))
    if not out:
        return None
    d = out[0] if isinstance(out[0], dict) else out[0].json["res"]
    labels, scores = d.get("label_names") or [], d.get("scores") or []
    if not labels:
        return None
    return int(labels[0]), float(scores[0])


def _detect_tesseract(rgb: np.ndarray) -> tuple[int, float] | None:
    try:
        import pytesseract

        from ..ocr.tesseract_engine import TesseractEngine

        if not TesseractEngine().available():
            return None
        osd = pytesseract.image_to_osd(rgb, output_type=pytesseract.Output.DICT)
        return int(osd.get("rotate", 0)) % 360, float(osd.get("orientation_conf", 0.0)) / 10.0
    except Exception:
        return None


def detect_rotation(rgb: np.ndarray) -> tuple[int, float, str]:
    """Возвращает (угол по часовой, уверенность, источник)."""
    r = _detect_paddle(rgb)
    if r is not None:
        return r[0], r[1], "paddle"
    r = _detect_tesseract(rgb)
    if r is not None:
        return r[0], r[1], "tesseract"
    return 0, 0.0, "none"


def rot90_matrix(k: int, w: int, h: int) -> np.ndarray:
    """Матрица координат для np.rot90(img, k)."""
    k %= 4
    if k == 0:
        return np.eye(3)
    if k == 1:   # (x, y) -> (y, w-1-x)
        return np.array([[0, 1, 0], [-1, 0, w - 1], [0, 0, 1]], dtype=np.float64)
    if k == 2:   # (x, y) -> (w-1-x, h-1-y)
        return np.array([[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1]], dtype=np.float64)
    return np.array([[0, -1, h - 1], [1, 0, 0], [0, 0, 1]], dtype=np.float64)  # k == 3: (x, y) -> (h-1-y, x)


def fix_orientation(rgb: np.ndarray, min_conf: float = 0.6) -> tuple[np.ndarray, np.ndarray, int, str]:
    """Поворачивает страницу текстом вверх."""
    angle, conf, src = detect_rotation(rgb)
    if angle == 0 or conf < min_conf:
        return rgb, np.eye(3), 0, src
    k = (angle // 90) % 4   # метка 270 = повёрнута на 270 по часовой, крутим обратно
    h, w = rgb.shape[:2]
    out = np.ascontiguousarray(np.rot90(rgb, k))
    return out, rot90_matrix(k, w, h), angle, src
