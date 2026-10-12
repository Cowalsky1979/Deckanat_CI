"""Работа с dekanat_core из Django: обработка, вопросы, смена типа, картинки."""
from __future__ import annotations

import hashlib
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from django.core.files.base import ContentFile
from django.db import connection, transaction
from PIL import Image, ImageDraw

from dekanat_core import pipeline
from dekanat_core.config.schema import get_doc_type, load_doc_types
from dekanat_core.io.loader import MultiPageError, UnsupportedFileError, sniff_format
from dekanat_core.layout.lines import group_lines
from dekanat_core.models import DocumentResult
from dekanat_core.preprocess.pipeline import map_bbox_back

from .models import ProcessingResult, QuestionAnswer, UploadedDocument

log = logging.getLogger(__name__)

MIME = {"png": "image/png", "jpeg": "image/jpeg", "pdf": "application/pdf", "webp": "image/webp",
        "bmp": "image/bmp", "tiff": "image/tiff"}


class ProcessingError(Exception):
    pass


def doc_types_public() -> list[dict]:
    return [cfg.public_dict() for cfg in load_doc_types().values()]


def _png_bytes(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


PREVIEW_MAX_SIDE = 1400


def _jpeg_preview(rgb: np.ndarray, max_side: int = PREVIEW_MAX_SIDE, quality: int = 82) -> bytes:
    """Уменьшенный jpeg для просмотра в браузере и Mini App."""
    img = Image.fromarray(rgb)
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _jpeg_bytes(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("DEKANAT_WORKERS", "1")), thread_name_prefix="ocr")


def _fail(doc: UploadedDocument, message: str) -> None:
    doc.status, doc.error = UploadedDocument.Status.ERROR, message
    doc.save(update_fields=["status", "error"])


def run_processing(doc_id, data: bytes, filename: str, doc_type: str) -> None:
    """OCR и извлечение полей, в фоновом потоке или сразу."""
    doc = UploadedDocument.objects.get(pk=doc_id)
    try:
        result, ctx = pipeline.process_document(data, filename, None if doc_type in ("", "auto", None) else doc_type,
                                                first_page_only=False)
    except (MultiPageError, UnsupportedFileError, KeyError) as exc:
        _fail(doc, str(exc.args[0] if exc.args else exc))
        return
    except Exception as exc:  # pragma: no cover
        log.exception("Ошибка обработки %s", doc.id)
        _fail(doc, f"Не удалось обработать документ: {exc}")
        return
    with transaction.atomic():
        pr = ProcessingResult(document=doc, result=result.to_dict(), transform=np.asarray(ctx.matrix).tolist(),
                              original_size=list(ctx.original_rgb.shape[1::-1]))
        pr.normalized_image.save(f"{doc.id}/normalized.png", ContentFile(_png_bytes(ctx.normalized_rgb)), save=False)
        pr.preview_image.save(f"{doc.id}/preview.jpg", ContentFile(_jpeg_preview(ctx.normalized_rgb)), save=False)
        pr.original_preview.save(f"{doc.id}/original_preview.jpg", ContentFile(_jpeg_preview(ctx.original_rgb)), save=False)
        pr.save()
        doc.doc_type, doc.type_confidence = result.doc_type, result.type_confidence
        doc.status, doc.timings = UploadedDocument.Status.DONE, result.timings
        doc.save()
    # если вместе с файлом пришел вопрос или проверка
    doc = UploadedDocument.objects.select_related("result").get(pk=doc_id)
    if doc.pending_question:
        ask(doc, doc.pending_question)
    elif doc.pending_check:
        check(doc)


def _worker(doc_id, data, filename, doc_type):
    try:
        run_processing(doc_id, data, filename, doc_type)
    except Exception:  # pragma: no cover
        log.exception("Фоновая обработка %s завершилась ошибкой", doc_id)
    finally:
        connection.close()


def _submit(doc_id, data, filename, doc_type) -> None:
    from django.conf import settings

    # в тестах БД в памяти и другой поток её не видит, поэтому без потока
    if getattr(settings, "DEKANAT_INLINE_WORKERS", False):
        run_processing(doc_id, data, filename, doc_type)
        return
    _executor.submit(_worker, doc_id, data, filename, doc_type)


def process_upload(data: bytes, filename: str, doc_type: str = "auto", *, source: str = "web",
                   telegram_user_id: str = "", question: str = "", check: bool = False,
                   wait: bool = True) -> UploadedDocument:
    """Создает документ и запускает обработку. wait=False - в фоне."""
    fmt = sniff_format(data)
    if fmt is None:
        raise ProcessingError("Поддерживаются JPG, PNG и одностраничный PDF")
    doc = UploadedDocument(original_name=filename[:255], mime=MIME.get(fmt, "application/octet-stream"),
                           size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                           selected_type=doc_type or "auto", source=source, telegram_user_id=telegram_user_id,
                           pending_question=(question or "").strip(), pending_check=bool(check))
    doc.file.save(filename or f"document.{fmt}", ContentFile(data), save=False)
    doc.save()
    if wait:
        run_processing(doc.pk, data, filename, doc_type)
        doc = UploadedDocument.objects.get(pk=doc.pk)
        if doc.status == UploadedDocument.Status.ERROR:
            raise ProcessingError(doc.error)
        return doc
    _submit(doc.pk, data, filename, doc_type)
    return doc


def load_result(doc: UploadedDocument) -> DocumentResult:
    return DocumentResult.from_dict(doc.result.result)


def ask(doc: UploadedDocument, question: str) -> QuestionAnswer:
    result = load_result(doc)
    ans = pipeline.answer_question(result, question)
    return QuestionAnswer.objects.create(
        document=doc, question=question, answerable=ans.answerable, value=ans.value, answer=ans.answer,
        sources=ans.sources, intent=ans.intent, field_key=ans.field_key or "",
    )


def check(doc: UploadedDocument) -> QuestionAnswer:
    from dekanat_core.qa.answer_builder import COMPLETENESS_QUESTION

    return ask(doc, COMPLETENESS_QUESTION)


def normalized_rgb(doc: UploadedDocument) -> np.ndarray:
    with doc.result.normalized_image.open("rb") as fh:
        return np.asarray(Image.open(fh).convert("RGB"))


def ensure_previews(doc: UploadedDocument) -> None:
    """Делает превью, если их нет (старые документы)."""
    pr = doc.result
    if pr.preview_image and pr.original_preview:
        return
    if not pr.preview_image:
        pr.preview_image.save(f"{doc.id}/preview.jpg", ContentFile(_jpeg_preview(normalized_rgb(doc))), save=False)
    if not pr.original_preview:
        try:
            from dekanat_core.io.loader import load_bytes

            with doc.file.open("rb") as fh:
                rgb = load_bytes(fh.read(), doc.original_name, first_page_only=True).rgb
            pr.original_preview.save(f"{doc.id}/original_preview.jpg", ContentFile(_jpeg_preview(rgb)), save=False)
        except Exception:  # pragma: no cover
            pr.original_preview.save(f"{doc.id}/original_preview.jpg", ContentFile(_jpeg_preview(normalized_rgb(doc))), save=False)
    pr.save()


@transaction.atomic
def change_type(doc: UploadedDocument, new_type: str) -> UploadedDocument:
    """Ручная смена типа, OCR заново не запускаем."""
    get_doc_type(new_type)  # кинет KeyError если тип неизвестен
    old = load_result(doc)
    ctx = pipeline.ProcessingContext()
    ctx.normalized_rgb = normalized_rgb(doc)
    ctx.matrix = np.asarray(doc.result.transform)
    ctx.lines = group_lines(old.ocr_lines)
    meta = {"timings": old.timings, "quality": {k: v for k, v in old.quality.items() if k not in ("steps", "ocr")},
            "steps": old.quality.get("steps", []), "ocr": old.quality.get("ocr", {}), "warnings": []}
    result = pipeline.build_result(ctx, new_type, meta)
    pr = doc.result
    pr.result = result.to_dict()
    pr.save()
    doc.selected_type, doc.doc_type, doc.type_confidence = new_type, result.doc_type, 1.0
    doc.save()
    doc.questions.all().delete()  # старые ответы были для другого типа
    return doc


def field_boxes(doc: UploadedDocument) -> list[dict]:
    """Координаты полей на нормализованной и исходной картинке."""
    result = load_result(doc)
    M = np.asarray(doc.result.transform)
    out = []
    for key, fv in result.fields.items():
        if not fv.bbox:
            continue
        out.append({
            "key": key, "label": fv.label, "found": fv.found, "kind": fv.kind, "bbox": list(fv.bbox),
            "label_bbox": list(fv.label_bbox) if fv.label_bbox else None,
            "polygon_original": map_bbox_back(fv.bbox, M),
        })
    return out


def _color(fv) -> tuple:
    if fv.kind == "mark":
        return (37, 99, 235) if fv.found else (220, 38, 38)
    return (22, 163, 74) if fv.found else (220, 38, 38)


def annotated_png(doc: UploadedDocument, only_key: str | None = None) -> bytes:
    result = load_result(doc)
    img = Image.fromarray(normalized_rgb(doc)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w = max(2, img.width // 400)
    for key, fv in result.fields.items():
        if not fv.bbox or (only_key and key != only_key):
            continue
        x1, y1, x2, y2 = fv.bbox
        pad = max(4, (y2 - y1) // 4)
        draw.rectangle([x1 - pad, y1 - pad, x2 + pad, y2 + pad], outline=_color(fv), width=w)
    img.thumbnail((1800, 1800), Image.LANCZOS)
    return _jpeg_bytes(img, 85)


def crop_png(doc: UploadedDocument, key: str, context: float = 0.6) -> bytes | None:
    result = load_result(doc)
    fv = result.fields.get(key)
    if fv is None or not fv.bbox:
        return None
    img = Image.fromarray(normalized_rgb(doc)).convert("RGB")
    x1, y1, x2, y2 = fv.bbox
    if fv.label_bbox:
        x1, y1 = min(x1, fv.label_bbox[0]), min(y1, fv.label_bbox[1])
        x2, y2 = max(x2, fv.label_bbox[2]), max(y2, fv.label_bbox[3])
    h = max(20, y2 - y1)
    px, py = int(0.1 * img.width), int(context * h) + 12
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(img.width, x2 + px), min(img.height, y2 + py)
    crop = img.crop((cx1, cy1, cx2, cy2))
    draw = ImageDraw.Draw(crop)
    bx1, by1, bx2, by2 = fv.bbox
    pad = max(3, h // 4)
    draw.rectangle([bx1 - cx1 - pad, by1 - cy1 - pad, bx2 - cx1 + pad, by2 - cy1 + pad], outline=_color(fv), width=3)
    crop.thumbnail((1200, 1200), Image.LANCZOS)
    return _jpeg_bytes(crop, 88)


def export_json(doc: UploadedDocument, document_id: str | None = None) -> dict:
    """Документ в формате results.json, answers берем из истории вопросов."""
    result = load_result(doc)
    return {
        "document_id": document_id or str(doc.id),
        "document_type": result.doc_type,
        "fields": result.fields_plain(),
        "validation": {"status": result.validation.status, "missing_fields": list(result.validation.missing_fields),
                       "sources": list(result.validation.sources)},
        "answers": [{"question_id": f"{doc.id}-Q{i + 1}", "answerable": q.answerable, "value": q.value,
                     "answer": q.answer, "sources": q.sources} for i, q in enumerate(doc.questions.all())],
    }
