"""Работа с dekanat_core из Django: обработка, вопросы, смена типа, картинки."""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from html import escape

import numpy as np
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from dekanat_core import pipeline
from dekanat_core.config.schema import get_doc_type, load_doc_types
from dekanat_core.io.loader import MultiPageError, UnsupportedFileError, sniff_format
from dekanat_core.layout.lines import group_lines
from dekanat_core.extract import normalizers as nz
from dekanat_core.models import MISSING_REASON_TEXT, NOT_FOUND, DocumentResult, FieldValue
from dekanat_core.preprocess.pipeline import map_bbox_back
from dekanat_core.rules.validator import validate

from .models import DocumentReview, Notification, ProcessingResult, Profile, QuestionAnswer, UploadedDocument

log = logging.getLogger(__name__)

MIME = {"png": "image/png", "jpeg": "image/jpeg", "pdf": "application/pdf", "webp": "image/webp",
        "bmp": "image/bmp", "tiff": "image/tiff"}


class ProcessingError(Exception):
    pass


class ReviewError(Exception):
    """Заявку нельзя создать (документ не обработан или уже отправлен)."""


class FieldEditError(Exception):
    """Поле нельзя исправить (нет такого поля, отметка, документ на рассмотрении)."""


# ---------- профили и заявки ----------

def owner_for(profile_id: str | None, telegram_user_id: str = "") -> Profile | None:
    """Владелец загрузки: профиль из заголовка, иначе профиль с таким Telegram id (загрузка из бота)."""
    if profile_id:
        try:
            p = Profile.objects.filter(pk=uuid.UUID(str(profile_id))).first()
        except ValueError:
            p = None
        if p:
            return p
    if telegram_user_id:
        return Profile.objects.filter(telegram_user_id=telegram_user_id).first()
    return None


def find_or_create_profile(role: str, name: str, telegram_user_id: str | None = None) -> tuple[Profile, bool]:
    """Входа нет, поэтому «аккаунт» — это роль + имя: то же имя открывает прежний кабинет.
    Если передан Telegram id, профиль ищется по нему, а профиль с тем же именем привязывается к аккаунту."""
    name = " ".join(name.split())
    profile = None
    if telegram_user_id:
        profile = Profile.objects.filter(telegram_user_id=telegram_user_id).first()
    if profile is None:
        # сравниваем в Python: iexact в SQLite не учитывает регистр кириллицы
        profile = next((p for p in Profile.objects.filter(role=role, telegram_user_id__isnull=True).order_by("created_at")
                        if p.name.casefold() == name.casefold()), None)
    created = profile is None
    if created:
        profile = Profile.objects.create(role=role, name=name, telegram_user_id=telegram_user_id)
    else:
        profile.role, profile.name = role, name
        if telegram_user_id:
            profile.telegram_user_id = telegram_user_id
        profile.save(update_fields=["role", "name", "telegram_user_id"])
    if profile.telegram_user_id:
        link_profile(profile)
    return profile, created


def link_profile(profile: Profile) -> int:
    """Привязывает к профилю ранние загрузки из бота с тем же Telegram id."""
    if not profile.telegram_user_id:
        return 0
    return UploadedDocument.objects.filter(owner__isnull=True, telegram_user_id=profile.telegram_user_id).update(owner=profile)


def _field_labels(result: dict) -> dict[str, str]:
    return {k: (v.get("label") or k) for k, v in (result.get("fields") or {}).items()}


def review_summary(doc: UploadedDocument) -> dict | None:
    """Краткий анализ ИИ для деканата и готовые причины отказа."""
    if doc.status != UploadedDocument.Status.DONE or not hasattr(doc, "result"):
        return None
    r = doc.result.result or {}
    validation = r.get("validation") or {}
    labels = _field_labels(r)
    try:
        rules = {k: f.rule for k, f in get_doc_type(doc.doc_type).field_map.items()}
    except KeyError:
        rules = {}
    fields = r.get("fields") or {}
    missing = [{"key": k, "label": labels.get(k, k), "rule": rules.get(k),
                "reason": (fields.get(k) or {}).get("missing_reason"),
                "reason_text": MISSING_REASON_TEXT.get((fields.get(k) or {}).get("missing_reason") or "", "")}
               for k in validation.get("missing_fields") or []]
    low_quality = bool(((r.get("quality") or {}).get("readability") or {}).get("low_quality"))
    mismatch = r.get("type_mismatch") or None
    doc_type_title = r.get("doc_type_title") or doc.doc_type
    manual = [{"key": k, "label": labels.get(k, k), "value": f.get("value"), "ocr_value": f.get("ocr_value")}
              for k, f in fields.items() if f.get("source") == "manual"]

    reasons: list[str] = []
    for m in missing:
        rule = f" (п. {m['rule']} Положения)" if m["rule"] else ""
        why = f": {m['reason_text']}" if m["reason_text"] else ""
        reasons.append(f"Отсутствует обязательное поле «{m['label']}»{rule}{why}")
    for m in manual:
        reasons.append(f"Поле «{m['label']}» исправлено студентом вручную ({m['value']}), OCR распознал: "
                       f"{m['ocr_value'] or 'не найдено'}. Нужно сверить с оригиналом")
    if low_quality:
        reasons.append("Снимок низкого качества: текст не читается, нужен скан или более чёткое фото")
    if mismatch:
        reasons.append(f"Загружен документ другого типа: похож на «{mismatch.get('detected_title') or mismatch.get('detected')}», "
                       f"а не на «{doc_type_title}»")

    if validation.get("status") == "document_ok":
        sources = ", ".join(s.replace("rule:", "") for s in validation.get("sources") or [])
        headline = f"Документ в порядке (пп. {sources})" if sources else "Документ в порядке"
    else:
        headline = "Не хватает полей: " + ", ".join(m["label"].lower() for m in missing) if missing else "Проверка не пройдена"
    if low_quality:
        headline = "Снимок низкого качества. " + headline

    return {
        "headline": headline,
        "validation_status": validation.get("status"),
        "validation_message": validation.get("message", ""),
        "missing": missing,
        "low_quality": low_quality,
        "type_mismatch": mismatch,
        "warnings": r.get("warnings") or [],
        "manual_fields": manual,
        "is_revision": doc.parent_id is not None,
        "suggested_reasons": reasons,
    }


def submit_for_review(doc: UploadedDocument, profile: Profile) -> DocumentReview:
    if doc.status != UploadedDocument.Status.DONE:
        raise ReviewError("Документ ещё не обработан")
    if DocumentReview.objects.filter(document=doc).exists():
        raise ReviewError("Документ уже отправлен в деканат")
    if doc.owner_id is None:  # загружен до выбора роли
        doc.owner = profile
        doc.save(update_fields=["owner"])
    return DocumentReview.objects.create(document=doc)


def decide(review: DocumentReview, reviewer: Profile, status: str, comment: str = "", reason_source: str = "") -> DocumentReview:
    review.status, review.reviewer = status, reviewer
    review.comment, review.reason_source = comment.strip(), reason_source
    review.decided_at, review.seen_by_dean = timezone.now(), True
    review.save()
    notify_decision(review)
    return review


# ---------- уведомления в Telegram ----------

DECISION_TITLES = {
    DocumentReview.Status.ACCEPTED: "✅ Деканат принял документ",
    DocumentReview.Status.REJECTED: "❌ Деканат отклонил документ",
    DocumentReview.Status.NEEDS_FIX: "✏️ Деканат просит исправить документ",
}


def _telegram_id_for(doc: UploadedDocument) -> str:
    if doc.telegram_user_id:
        return doc.telegram_user_id
    if doc.owner_id and doc.owner and doc.owner.telegram_user_id:
        return doc.owner.telegram_user_id
    return ""


def decision_text(review: DocumentReview) -> str:
    """HTML-сообщение о решении для Telegram."""
    doc = review.document
    title = ""
    if hasattr(doc, "result"):
        title = (doc.result.result or {}).get("doc_type_title") or doc.doc_type
    head = DECISION_TITLES.get(review.status, "Решение деканата")
    lines = [f"<b>{head}</b>", f"📄 {escape(title or doc.original_name or 'документ')}"]
    if review.comment:
        lines.append(f"💬 {escape(review.comment)}")
    if review.reviewer:
        lines.append(f"👤 {escape(review.reviewer.name)}")
    if review.status == DocumentReview.Status.NEEDS_FIX:
        lines.append("Загрузите исправленную версию: на сайте в кабинете нажмите «Загрузить исправленную версию».")
    return "\n".join(lines)


def notify_decision(review: DocumentReview) -> Notification | None:
    tg = _telegram_id_for(review.document)
    if not tg or review.status == DocumentReview.Status.PENDING:
        return None
    return Notification.objects.create(telegram_user_id=tg, document=review.document, kind="review_decided",
                                       text=decision_text(review))


def pending_notifications(limit: int = 50) -> list[Notification]:
    return list(Notification.objects.filter(sent_at__isnull=True).order_by("created_at")[:limit])


def mark_notification_sent(n: Notification, error: str = "") -> None:
    n.sent_at, n.error = timezone.now(), error[:500]
    n.save(update_fields=["sent_at", "error"])


def doc_types_public() -> list[dict]:
    return [cfg.public_dict() for cfg in load_doc_types().values()]


def _png_bytes(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


PREVIEW_MAX_SIDE = 1400


def _jpeg_preview(rgb: np.ndarray, max_side: int = PREVIEW_MAX_SIDE, quality: int = 82) -> bytes:
    """Уменьшенный jpeg для просмотра в браузере."""
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
    doc = UploadedDocument.objects.select_related("result", "parent", "parent__review").get(pk=doc_id)
    if doc.pending_question:
        ask(doc, doc.pending_question)
    elif doc.pending_check:
        check(doc)
    autosubmit_revision(doc)


def _worker(doc_id, data, filename, doc_type):
    try:
        run_processing(doc_id, data, filename, doc_type)
    except Exception:  # pragma: no cover
        log.exception("Фоновая обработка %s завершилась ошибкой", doc_id)
    finally:
        connection.close()


def _submit(doc_id, data, filename, doc_type) -> None:
    from django.conf import settings

    # в тестах TestCase держит всё в одной незакоммиченной транзакции, другой поток её не видит
    if getattr(settings, "DEKANAT_INLINE_WORKERS", False):
        run_processing(doc_id, data, filename, doc_type)
        return
    _executor.submit(_worker, doc_id, data, filename, doc_type)


def autosubmit_revision(doc: UploadedDocument) -> DocumentReview | None:
    """Исправленная версия сразу уходит в деканат, если прежняя версия была у него на рассмотрении."""
    if doc.status != UploadedDocument.Status.DONE or not doc.parent_id or not doc.owner_id:
        return None
    if not DocumentReview.objects.filter(document=doc.parent_id).exists() or DocumentReview.objects.filter(document=doc).exists():
        return None
    return DocumentReview.objects.create(document=doc)


def parent_for_revision(parent_id, owner: Profile | None) -> UploadedDocument:
    """Документ, исправленную версию которого загружают: должен быть возвращён или отклонён деканатом."""
    parent = UploadedDocument.objects.select_related("review", "owner").filter(pk=parent_id).first()
    if parent is None:
        raise ProcessingError("Исходный документ не найден")
    if parent.owner_id and owner is not None and parent.owner_id != owner.id:
        raise ProcessingError("Это документ другого студента")
    review = getattr(parent, "review", None)
    if review is None or review.status not in (DocumentReview.Status.NEEDS_FIX, DocumentReview.Status.REJECTED):
        raise ProcessingError("Исправленную версию можно загрузить только для документа, который деканат вернул или отклонил")
    return parent


def process_upload(data: bytes, filename: str, doc_type: str = "auto", *, source: str = "web",
                   telegram_user_id: str = "", question: str = "", check: bool = False,
                   wait: bool = True, owner: Profile | None = None, parent=None) -> UploadedDocument:
    """Создает документ и запускает обработку. wait=False - в фоне. parent - прежняя версия документа."""
    fmt = sniff_format(data)
    if fmt is None:
        raise ProcessingError("Поддерживаются JPG, PNG и одностраничный PDF")
    parent_doc = parent_for_revision(parent, owner) if parent else None
    if parent_doc is not None:
        owner = owner or parent_doc.owner
        telegram_user_id = telegram_user_id or parent_doc.telegram_user_id
        if doc_type in ("", "auto", None) and parent_doc.doc_type:
            doc_type = parent_doc.doc_type
    doc = UploadedDocument(original_name=filename[:255], mime=MIME.get(fmt, "application/octet-stream"),
                           size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                           selected_type=doc_type or "auto", source=source, telegram_user_id=telegram_user_id,
                           owner=owner, parent=parent_doc,
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


# ---------- ручная правка полей ----------

def update_field(doc: UploadedDocument, key: str, value: str, profile: Profile | None = None) -> UploadedDocument:
    """Студент исправляет значение текстового поля. Значение OCR сохраняется рядом, проверка пересчитывается.
    Пустая строка возвращает значение OCR."""
    if doc.status != UploadedDocument.Status.DONE or not hasattr(doc, "result"):
        raise FieldEditError("Документ ещё не обработан")
    if profile is not None and profile.role == Profile.Role.DEAN:
        raise FieldEditError("Поля исправляет студент, деканат видит исходное и исправленное значения")
    if profile is not None and doc.owner_id and doc.owner_id != profile.id:
        raise FieldEditError("Это документ другого студента")
    review = getattr(doc, "review", None)
    if review is not None and review.status in (DocumentReview.Status.PENDING, DocumentReview.Status.ACCEPTED):
        raise FieldEditError("Документ на рассмотрении или уже принят: исправить поля нельзя")
    cfg = get_doc_type(doc.doc_type)
    spec = cfg.field_map.get(key)
    if spec is None:
        raise FieldEditError(f"У типа «{cfg.title}» нет поля {key}")
    if spec.is_mark:
        raise FieldEditError("Подпись и печать проверяются как графические элементы, вручную их отметить нельзя (п. 2.3)")

    result = load_result(doc)
    fv = result.fields[key]
    ocr_value = fv.ocr_value if fv.is_manual else fv.value
    raw = " ".join((value or "").split())
    if not raw:
        # откат к OCR
        new = FieldValue(key=key, label=spec.label, value=ocr_value, raw=fv.raw, bbox=fv.bbox, label_bbox=fv.label_bbox,
                         confidence=fv.confidence, found=ocr_value != NOT_FOUND, kind="text",
                         missing_reason=fv.missing_reason if ocr_value == NOT_FOUND else None)
    else:
        if spec.type == "date" and nz.parse_date(raw) is None:
            raise FieldEditError("Не удалось разобрать дату: укажите её в виде ДД.ММ.ГГГГ")
        if spec.type == "int" and not any(ch.isdigit() for ch in raw):
            raise FieldEditError("Укажите число")
        norm = nz.normalize(spec.type, raw, values=spec.values)
        if nz.is_empty_value(norm) or norm == NOT_FOUND:
            raise FieldEditError("Не удалось разобрать значение")
        new = FieldValue(key=key, label=spec.label, value=norm, raw=fv.raw, bbox=fv.bbox, label_bbox=fv.label_bbox,
                         confidence=fv.confidence, found=True, kind="text", source="manual", ocr_value=ocr_value,
                         missing_reason=fv.missing_reason if ocr_value == NOT_FOUND else None)
    result.fields[key] = new
    result.validation = validate(cfg, result.fields)
    pr = doc.result
    pr.result = result.to_dict()
    pr.save(update_fields=["result", "updated_at"])
    return doc


def _plain_value(fv: dict) -> str:
    if fv.get("kind") == "mark":
        return "есть" if fv.get("found") else "отсутствует"
    v = fv.get("value")
    return str(v) if v is not None else NOT_FOUND


def field_diff(doc: UploadedDocument) -> dict | None:
    """Что изменилось в исправленной версии по сравнению с прежней (для деканата и студента)."""
    parent = doc.parent
    if parent is None or doc.status != UploadedDocument.Status.DONE or parent.status != UploadedDocument.Status.DONE:
        return None
    if not hasattr(doc, "result") or not hasattr(parent, "result"):
        return None
    new, old = doc.result.result or {}, parent.result.result or {}
    nf, of = new.get("fields") or {}, old.get("fields") or {}
    rows = []
    for key, f in nf.items():
        o = of.get(key)
        before = _plain_value(o) if o else "—"
        after = _plain_value(f)
        rows.append({"key": key, "label": f.get("label") or key, "kind": f.get("kind"), "before": before, "after": after,
                     "changed": before != after, "fixed": (o is None or not o.get("found")) and bool(f.get("found")),
                     "manual": f.get("source") == "manual"})
    ov, nv = old.get("validation") or {}, new.get("validation") or {}
    return {
        "parent_id": str(parent.id),
        "parent_created_at": parent.created_at.isoformat(),
        "parent_review_status": parent.review.status if hasattr(parent, "review") else None,
        "parent_review_comment": parent.review.comment if hasattr(parent, "review") else "",
        "before_status": ov.get("status"), "after_status": nv.get("status"),
        "before_missing": ov.get("missing_fields") or [], "after_missing": nv.get("missing_fields") or [],
        "changed_count": sum(1 for r in rows if r["changed"]),
        "rows": rows,
    }


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
    """Документ в формате results.json: только результат OCR (ручные правки не подставляются, п. 2.2),
    answers берем из истории вопросов."""
    result = load_result(doc)
    ocr_fields = result.ocr_fields()
    validation = validate(get_doc_type(result.doc_type), ocr_fields)
    return {
        "document_id": document_id or str(doc.id),
        "document_type": result.doc_type,
        "fields": {k: v.value for k, v in ocr_fields.items()},
        "validation": {"status": validation.status, "missing_fields": list(validation.missing_fields),
                       "sources": list(validation.sources)},
        "answers": [{"question_id": f"{doc.id}-Q{i + 1}", "answerable": q.answerable, "value": q.value,
                     "answer": q.answer, "sources": q.sources} for i, q in enumerate(doc.questions.all())],
    }


# ---------- выгрузка заявок для деканата ----------

REVIEW_TITLES = {s.value: s.label for s in DocumentReview.Status}

CSV_HEADER = ["ID документа", "Студент", "Тип документа", "Файл", "Загружен", "Отправлен в деканат", "Источник",
              "Проверка ИИ", "Не хватает полей", "Исправлено вручную", "Версия", "Исходный документ",
              "Решение", "Решение принял", "Дата решения", "Комментарий"]


def reviews_csv(mode: str = "all") -> str:
    """CSV (разделитель ';', BOM для Excel) по заявкам: все, только входящие или только обработанные."""
    qs = UploadedDocument.objects.select_related("result", "owner", "review", "review__reviewer").filter(review__isnull=False)
    if mode == "pending":
        qs = qs.filter(review__status=DocumentReview.Status.PENDING)
    elif mode == "decided":
        qs = qs.exclude(review__status=DocumentReview.Status.PENDING)
    qs = qs.order_by("-review__submitted_at")

    def fmt(dt):
        return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else ""

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for doc in qs:
        r = doc.review
        res = doc.result.result if doc.status == UploadedDocument.Status.DONE and hasattr(doc, "result") else {}
        validation = res.get("validation") or {}
        fields = res.get("fields") or {}
        labels = {k: (f.get("label") or k) for k, f in fields.items()}
        missing = ", ".join(labels.get(k, k) for k in validation.get("missing_fields") or [])
        manual = ", ".join(labels.get(k, k) for k, f in fields.items() if f.get("source") == "manual")
        check = {"document_ok": "в порядке", "missing_fields": "не хватает сведений"}.get(validation.get("status"), doc.get_status_display())
        w.writerow([
            str(doc.id), doc.owner.name if doc.owner else "", res.get("doc_type_title") or doc.doc_type, doc.original_name,
            fmt(doc.created_at), fmt(r.submitted_at), doc.get_source_display(), check, missing, manual,
            "исправленная" if doc.parent_id else "первая", str(doc.parent_id) if doc.parent_id else "",
            REVIEW_TITLES.get(r.status, r.status), r.reviewer.name if r.reviewer else "", fmt(r.decided_at), r.comment,
        ])
    return "﻿" + buf.getvalue()
