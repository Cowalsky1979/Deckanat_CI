"""Структуры данных ядра."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

NOT_FOUND = "не найдено"

BBox = tuple[int, int, int, int]  # x1, y1, x2, y2 в пикселях нормализованного изображения


def to_jsonable(obj):
    """Переводит numpy-типы в обычные питоновские (для JSON)."""
    import numpy as np

    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


@dataclass
class OcrLine:
    text: str
    bbox: BBox
    conf: float
    engine: str = ""


@dataclass
class FieldValue:
    key: str
    label: str
    value: Any                      # str | bool
    raw: str = ""
    bbox: Optional[BBox] = None     # bbox значения (или метки, если значение пустое)
    label_bbox: Optional[BBox] = None
    confidence: float = 0.0
    found: bool = False             # поле заполнено или отметка есть
    kind: str = "text"              # text | mark

    def to_dict(self) -> dict:
        return to_jsonable(asdict(self))


@dataclass
class Validation:
    status: str                     # document_ok | missing_fields
    missing_fields: list[str]
    sources: list[str]
    message: str = ""

    def to_dict(self) -> dict:
        return to_jsonable(asdict(self))


@dataclass
class Answer:
    question: str
    answerable: bool
    value: Optional[str]
    answer: str
    sources: list[str]
    intent: str = ""
    field_key: Optional[str] = None     # для подсветки на снимке

    def to_result(self, question_id: str) -> dict:
        return {
            "question_id": question_id,
            "answerable": self.answerable,
            "value": self.value,
            "answer": self.answer,
            "sources": list(self.sources),
        }

    def to_dict(self) -> dict:
        return to_jsonable(asdict(self))


@dataclass
class DocumentResult:
    doc_type: str
    doc_type_title: str
    type_confidence: float
    type_auto: bool
    fields: dict[str, FieldValue]
    validation: Validation
    ocr_text: str
    ocr_lines: list[OcrLine]
    image_size: tuple[int, int]     # (w, h) нормализованного изображения
    quality: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    type_candidates: list[dict] = field(default_factory=list)
    type_mismatch: Optional[dict] = None     # заполняется, если выбран не тот тип

    def fields_plain(self) -> dict[str, Any]:
        """Поля в формате results.json."""
        return {k: v.value for k, v in self.fields.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentResult":
        fields = {k: FieldValue(**{**v, "bbox": tuple(v["bbox"]) if v.get("bbox") else None,
                                   "label_bbox": tuple(v["label_bbox"]) if v.get("label_bbox") else None})
                  for k, v in d["fields"].items()}
        v = d["validation"]
        return cls(
            doc_type=d["doc_type"], doc_type_title=d.get("doc_type_title", ""),
            type_confidence=d.get("type_confidence", 1.0), type_auto=d.get("type_auto", False),
            fields=fields,
            validation=Validation(status=v["status"], missing_fields=list(v["missing_fields"]),
                                  sources=list(v["sources"]), message=v.get("message", "")),
            ocr_text=d.get("ocr_text", ""),
            ocr_lines=[OcrLine(text=l["text"], bbox=tuple(l["bbox"]), conf=l.get("conf", 0.0), engine=l.get("engine", ""))
                       for l in d.get("ocr_lines", [])],
            image_size=tuple(d.get("image_size", (0, 0))), quality=d.get("quality", {}), timings=d.get("timings", {}),
            warnings=list(d.get("warnings", [])), type_candidates=list(d.get("type_candidates", [])),
            type_mismatch=d.get("type_mismatch"),
        )

    def to_dict(self) -> dict:
        return to_jsonable({
            "doc_type": self.doc_type,
            "doc_type_title": self.doc_type_title,
            "type_confidence": self.type_confidence,
            "type_auto": self.type_auto,
            "type_candidates": self.type_candidates,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "validation": self.validation.to_dict(),
            "ocr_text": self.ocr_text,
            "ocr_lines": [asdict(l) for l in self.ocr_lines],
            "image_size": list(self.image_size),
            "quality": self.quality,
            "timings": self.timings,
            "warnings": self.warnings,
            "type_mismatch": self.type_mismatch,
        })
