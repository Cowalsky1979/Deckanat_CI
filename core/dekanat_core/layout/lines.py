"""Сборка OCR-боксов в строки и разбор "Метка: значение"."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import BBox, OcrLine


@dataclass
class TextLine:
    text: str
    bbox: BBox
    conf: float
    parts: list[OcrLine] = field(default_factory=list)

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def group_lines(ocr: list[OcrLine]) -> list[TextLine]:
    """Склеивает боксы в строки, если они пересекаются по вертикали больше чем на 50%."""
    items = sorted(ocr, key=lambda l: ((l.bbox[1] + l.bbox[3]) / 2, l.bbox[0]))
    rows: list[list[OcrLine]] = []
    for it in items:
        cy = (it.bbox[1] + it.bbox[3]) / 2
        h = max(1, it.bbox[3] - it.bbox[1])
        placed = False
        for row in rows:
            ry1 = min(r.bbox[1] for r in row)
            ry2 = max(r.bbox[3] for r in row)
            rh = max(1, ry2 - ry1)
            overlap = min(it.bbox[3], ry2) - max(it.bbox[1], ry1)
            if overlap > 0.5 * min(h, rh) and abs(cy - (ry1 + ry2) / 2) < 0.7 * max(h, rh):
                row.append(it)
                placed = True
                break
        if not placed:
            rows.append([it])
    out: list[TextLine] = []
    for row in rows:
        row.sort(key=lambda l: l.bbox[0])
        bbox = row[0].bbox
        for r in row[1:]:
            bbox = _union(bbox, r.bbox)
        text = " ".join(r.text.strip() for r in row)
        conf = sum(r.conf for r in row) / len(row)
        out.append(TextLine(text=re.sub(r"\s+", " ", text).strip(), bbox=bbox, conf=conf, parts=row))
    out.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    return out


_SEP_RE = re.compile(r"\s*[:：]\s*")


def split_label_value(line: TextLine) -> tuple[str, str, BBox | None, BBox | None]:
    """Возвращает (метка, значение, bbox метки, bbox значения)."""
    text = line.text
    m = _SEP_RE.search(text)
    if not m:
        return text, "", line.bbox, None
    label = text[: m.start()].strip()
    value = text[m.end():].strip()

    # ищем часть с двоеточием
    label_bbox: BBox | None = None
    value_bbox: BBox | None = None
    acc = 0
    for part in line.parts:
        ptext = part.text.strip()
        start, end = acc, acc + len(ptext)
        acc = end + 1
        if start <= m.start() < end + 1:
            frac = (m.end() - start) / max(1, len(ptext))
            x1, y1, x2, y2 = part.bbox
            xs = x1 + int((x2 - x1) * min(1.0, frac))
            label_bbox = (x1, y1, xs, y2) if label_bbox is None else _union(label_bbox, (x1, y1, xs, y2))
            if frac < 0.98:
                value_bbox = (xs, y1, x2, y2)
        elif end <= m.start():
            label_bbox = part.bbox if label_bbox is None else _union(label_bbox, part.bbox)
        else:
            value_bbox = part.bbox if value_bbox is None else _union(value_bbox, part.bbox)
    return label, value, label_bbox or line.bbox, value_bbox


_OK_CHARS = set(" .,:;-–—«»()/№\"'!?%+")


def is_junk_line(text: str, conf: float = 1.0) -> bool:
    """Проверяет, что строка это мусор с фона фото, а не текст документа."""
    t = text.strip()
    if not t:
        return True
    letters = [c for c in t if c.isalpha()]
    digits = sum(c.isdigit() for c in t)
    cyr = sum(("а" <= c.lower() <= "я") or c.lower() == "ё" for c in letters)
    if not letters and digits < 2:
        return True
    if conf < 0.45:
        return True
    weird = sum(1 for c in t if not (c.isalnum() or c in _OK_CHARS))
    if weird / max(1, len(t)) > 0.2:
        return True
    if letters and cyr / len(letters) < 0.5 and digits < 4:
        return True
    if len(t) <= 2 and digits == 0:
        return True
    # нормальное слово: только кириллица и цифры (без пунктуации)
    tokens = [tok.strip("«»\"'.,:;()№-–—/!?") for tok in t.split()]
    tokens = [tok for tok in tokens if tok]
    if len(tokens) >= 4:
        good = sum(1 for tok in tokens if all(c.isdigit() or ("а" <= c.lower() <= "я") or c.lower() == "ё" or c == "." for c in tok))
        if good / len(tokens) < 0.5:
            return True
    return False


def full_text(lines: list[TextLine], *, drop_junk: bool = True) -> str:
    """Текст для показа пользователю, без мусорных строк."""
    kept = [l.text for l in lines if not (drop_junk and is_junk_line(l.text, l.conf))]
    return "\n".join(kept)
