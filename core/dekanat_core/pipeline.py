"""Основной пайплайн: файл -> OCR -> поля -> проверка, вопрос -> ответ."""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

from .classify.doc_type import classify
from .config.schema import DocTypeConfig, get_doc_type, load_doc_types
from .extract.extractor import extract_text_fields
from .io.loader import LoadedImage, load_bytes
from .layout.lines import TextLine, full_text, group_lines
from .marks.detect import detect_marks
from .models import Answer, DocumentResult, FieldValue
from .ocr import ensemble
from .preprocess import pipeline as pre
from .qa.answer_builder import answer_question as _answer, check_document as _check
from .rules.validator import validate

log = logging.getLogger(__name__)


class ProcessingContext:
    """Промежуточные данные для подсветки и смены типа."""

    def __init__(self):
        self.original_rgb: Optional[np.ndarray] = None
        self.normalized_rgb: Optional[np.ndarray] = None
        self.matrix: Optional[np.ndarray] = None
        self.lines: list[TextLine] = []
        self.ocr_info: dict = {}


def _all_labels() -> list[list[str]]:
    """Метки текстовых полей по типам (для оценки качества OCR)."""
    return [[f.label for f in cfg.text_fields] for cfg in load_doc_types().values()]


def analyze_image(rgb: np.ndarray, *, preprocess: bool = True) -> tuple[ProcessingContext, dict]:
    """OCR и разбивка на строки."""
    t0 = time.perf_counter()
    ctx = ProcessingContext()
    ctx.original_rgb = rgb
    timings: dict = {}
    if preprocess:
        pr = pre.run(rgb)
        ctx.normalized_rgb, ctx.matrix = pr.rgb, pr.matrix
        quality = pr.quality
        steps = pr.steps
    else:
        ctx.normalized_rgb, ctx.matrix = rgb, np.eye(3)
        quality, steps = {}, []
    timings["preprocess"] = round(time.perf_counter() - t0, 3)

    t1 = time.perf_counter()
    ocr_lines, info = ensemble.recognize(ctx.normalized_rgb, expected_labels=_all_labels())
    ctx.ocr_info = info
    ctx.lines = group_lines(ocr_lines)
    timings["ocr"] = round(time.perf_counter() - t1, 3)
    return ctx, {"timings": timings, "quality": quality, "steps": steps, "ocr": info}


def build_result(ctx: ProcessingContext, doc_type: Optional[str], meta: dict) -> DocumentResult:
    """Извлечение полей и проверка для выбранного типа."""
    t2 = time.perf_counter()
    auto = doc_type in (None, "", "auto")
    candidates: list[dict] = []
    if auto:
        doc_type, conf, candidates = classify(ctx.lines)
    else:
        conf = 1.0
        _, _, candidates = classify(ctx.lines)
    cfg = get_doc_type(doc_type)

    fields: dict[str, FieldValue] = {}
    fields.update(extract_text_fields(cfg, ctx.lines))
    fields.update(detect_marks(ctx.normalized_rgb, ctx.lines, cfg.mark_fields))
    fields = {spec.key: fields[spec.key] for spec in cfg.fields}
    validation = validate(cfg, fields)
    timings = dict(meta.get("timings", {}))
    timings["extract"] = round(time.perf_counter() - t2, 3)

    warnings = list(meta.get("warnings", []))
    # читаемость: уверенность OCR, доля найденных меток, высота текста
    confs = [l.conf for ln in ctx.lines for l in ln.parts]
    mean_conf = float(np.mean(confs)) if confs else 0.0
    labels_found = sum(1 for f in cfg.text_fields if fields[f.key].label_bbox is not None)
    label_ratio = labels_found / max(1, len(cfg.text_fields))
    low_quality = mean_conf < 0.75 or label_ratio < 0.6
    readability = {"mean_ocr_conf": round(mean_conf, 3), "labels_found_ratio": round(label_ratio, 2), "low_quality": low_quality}
    if low_quality:
        warnings.append("Снимок низкого качества: текст мелкий или нечёткий, распознавание ненадёжно. "
                        "Сфотографируйте документ ближе, ровно и при хорошем освещении (или пришлите скан/PDF).")
    if auto and conf < 0.5:
        warnings.append("Тип документа определён с низкой уверенностью — проверьте выбор типа.")
    type_mismatch = None
    if not auto and candidates:
        # тип выбран вручную, но документ похож на другой, просто предупреждаем
        best = candidates[0]
        chosen = next((c for c in candidates if c["key"] == cfg.key), None)
        if best["key"] != cfg.key and best["score"] >= 0.5 and (chosen is None or best["score"] >= 2 * max(0.05, chosen["score"])):
            type_mismatch = {"detected": best["key"], "detected_title": best["title"], "score": best["score"]}
            warnings.append(f"Похоже, выбран неправильный тип документа: загруженный документ больше похож на "
                            f"«{best['title']}». Проверьте тип или смените его.")
    h, w = ctx.normalized_rgb.shape[:2]
    return DocumentResult(
        doc_type=cfg.key, doc_type_title=cfg.title, type_confidence=conf, type_auto=auto,
        fields=fields, validation=validation, ocr_text=full_text(ctx.lines),
        ocr_lines=[l for ln in ctx.lines for l in ln.parts],
        image_size=(w, h), quality=dict(meta.get("quality", {}), steps=meta.get("steps", []), ocr=meta.get("ocr", {}),
                                        readability=readability),
        timings=timings, warnings=warnings, type_candidates=candidates, type_mismatch=type_mismatch,
    )


def process_document(data: bytes, filename: str = "", doc_type: Optional[str] = None,
                     *, first_page_only: bool = False, preprocess: bool = True) -> tuple[DocumentResult, ProcessingContext]:
    loaded: LoadedImage = load_bytes(data, filename, first_page_only=first_page_only)
    ctx, meta = analyze_image(loaded.rgb, preprocess=preprocess)
    meta["warnings"] = loaded.warnings
    result = build_result(ctx, doc_type, meta)
    return result, ctx


def answer_question(result: DocumentResult, question: str) -> Answer:
    return _answer(result, get_doc_type(result.doc_type), question)


def check_document(result: DocumentResult) -> Answer:
    return _check(result, get_doc_type(result.doc_type))


def doc_type_config(result: DocumentResult) -> DocTypeConfig:
    return get_doc_type(result.doc_type)
