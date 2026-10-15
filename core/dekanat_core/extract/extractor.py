"""Извлечение текстовых полей по конфигу типа документа из строк OCR."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..config.schema import DocTypeConfig, FieldSpec
from ..layout.lines import TextLine, split_label_value
from ..models import MISSING_EMPTY, MISSING_LABEL, NOT_FOUND, FieldValue
from ..settings import get_settings
from . import normalizers as nz


_LAT2CYR_LOWER = str.maketrans({"a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о",
                                "p": "р", "t": "т", "x": "х", "y": "у", "u": "и", "r": "г", "n": "п", "w": "ш"})


def _norm_label(s: str) -> str:
    s = s.lower().replace("ё", "е")
    # OCR часто читает короткие метки латиницей (Kypc), переводим в кириллицу
    if re.search(r"[а-я]", s) or len(s) <= 6:
        s = s.translate(_LAT2CYR_LOWER)
    s = re.sub(r"[^a-zа-я0-9 ]+", " ", s)
    return nz.clean_spaces(s)


def _label_score(candidate: str, spec: FieldSpec) -> float:
    c = _norm_label(candidate)
    if not c:
        return 0.0
    target = _norm_label(spec.label)
    score = max(fuzz.ratio(c, target), fuzz.token_set_ratio(c, target))
    # штраф за разную длину, чтобы не путать "Дата начала отпуска" и "Дата окончания отпуска"
    if abs(len(c) - len(target)) > max(4, 0.4 * len(target)):
        score -= 15
    return score


def _split_by_label_prefix(ln: TextLine, cfg: DocTypeConfig, threshold: int):
    """Строка без двоеточия: если начало похоже на метку, остаток считаем значением."""
    text = ln.text.strip()
    words = text.split()
    best = None
    for spec in cfg.text_fields:
        n_words = len(spec.label.split())
        for extra in (0, 1):
            k = n_words + extra
            if k > len(words) - 1:
                continue
            candidate = " ".join(words[:k])
            s = _label_score(candidate, spec)
            if s >= threshold and (best is None or s > best[0]):
                best = (s, k)
    if best is None:
        return None
    k = best[1]
    label = " ".join(words[:k])
    value = " ".join(words[k:])
    # bbox значения по доле символов
    x1, y1, x2, y2 = ln.bbox
    frac = (len(label) + 1) / max(1, len(text))
    xs = x1 + int((x2 - x1) * min(0.95, frac))
    return label, value, (x1, y1, xs, y2), (xs, y1, x2, y2)


def extract_text_fields(cfg: DocTypeConfig, lines: list[TextLine]) -> dict[str, FieldValue]:
    settings = get_settings().get("extract", {})
    threshold = settings.get("label_match_threshold", 82)
    empty_pattern = settings.get("empty_pattern", r"^[\s_\-—–·.,:;|~]*$")

    parsed = []
    for ln in lines:
        label, value, lb, vb = split_label_value(ln)
        if not value:
            # OCR потерял двоеточие, ищем метку в начале строки
            label, value, lb, vb = _split_by_label_prefix(ln, cfg, threshold) or (label, value, lb, vb)
        parsed.append((ln, label, value, lb, vb))

    # оценки поле x строка, сначала берем лучшие совпадения
    scored: list[tuple[float, int, int]] = []
    for fi, spec in enumerate(cfg.text_fields):
        for li, (ln, label, value, lb, vb) in enumerate(parsed):
            if not label:
                continue
            s = _label_score(label, spec)
            if s >= threshold:
                scored.append((s, fi, li))
    scored.sort(reverse=True)
    used_lines: set[int] = set()
    assigned: dict[int, int] = {}
    for s, fi, li in scored:
        if fi in assigned or li in used_lines:
            continue
        assigned[fi] = li
        used_lines.add(li)

    result: dict[str, FieldValue] = {}
    for fi, spec in enumerate(cfg.text_fields):
        if fi not in assigned:
            result[spec.key] = FieldValue(key=spec.key, label=spec.label, value=NOT_FOUND, raw="",
                                          confidence=0.0, found=False, kind="text", missing_reason=MISSING_LABEL)
            continue
        ln, label, value, lb, vb = parsed[assigned[fi]]
        raw = value
        if nz.is_empty_value(raw, empty_pattern):
            result[spec.key] = FieldValue(key=spec.key, label=spec.label, value=NOT_FOUND, raw=raw,
                                          bbox=vb or lb, label_bbox=lb, confidence=ln.conf, found=False, kind="text",
                                          missing_reason=MISSING_EMPTY)
            continue
        norm = nz.normalize(spec.type, raw, values=spec.values)
        if nz.is_empty_value(norm, empty_pattern):
            norm = NOT_FOUND
        found = norm != NOT_FOUND
        result[spec.key] = FieldValue(key=spec.key, label=spec.label, value=norm, raw=raw,
                                      bbox=vb or lb, label_bbox=lb, confidence=ln.conf, found=found, kind="text",
                                      missing_reason=None if found else MISSING_EMPTY)
    return result


def find_anchor_line(lines: list[TextLine], anchor: str, threshold: int = 80) -> TextLine | None:
    """Ищет строку с якорной надписью (например "Подпись студента")."""
    a = _norm_label(anchor)
    best, best_s = None, 0
    for ln in lines:
        t = _norm_label(ln.text)
        s = fuzz.partial_ratio(a, t)
        if s > best_s:
            best, best_s = ln, s
    return best if best_s >= threshold else None


def anchor_bbox(line: TextLine, anchor: str):
    """bbox самой надписи внутри строки (строка могла склеиться с подписью или печатью)."""
    a = _norm_label(anchor)
    best, best_s = None, 0
    for part in line.parts:
        s = fuzz.partial_ratio(a, _norm_label(part.text))
        if s > best_s:
            best, best_s = part, s
    if best is None:
        return line.bbox
    x1, y1, x2, y2 = best.bbox
    text = best.text
    m = re.search(r"[:：]", text)
    if m and len(text) > m.end() + 1:
        frac = (m.end()) / len(text)
        x2 = x1 + int((x2 - x1) * frac)
    return (x1, y1, x2, y2)
