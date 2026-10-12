"""Разбор вопроса студента по правилам.

Порядок: decision -> completeness -> field -> faq -> not_established -> no_info.
Если ничего не подошло, отказываем (п. 2.4, 6.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import yaml
from rapidfuzz import fuzz

from ..config.schema import DocTypeConfig, FieldSpec
from ..settings import CONFIG_DIR, get_settings


@dataclass
class Intent:
    kind: str                           # decision | completeness | field | faq | not_established | no_info
    field_key: Optional[str] = None
    faq: Optional[dict] = None
    note: Optional[dict] = None
    score: float = 0.0
    debug: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_intents() -> dict:
    with open(CONFIG_DIR / "intents.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def normalize_question(q: str) -> str:
    s = q.lower().replace("ё", "е")
    s = s.replace("“", '"').replace("”", '"').replace("„", '"').replace("«", '"').replace("»", '"')
    s = re.sub(r"[^\w\s\"\-.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _any_pattern(q: str, patterns: list[str], threshold: int = 88) -> float:
    best = 0.0
    for p in patterns:
        p = p.lower().replace("ё", "е")
        if p in q:
            return 100.0
        s = fuzz.partial_ratio(p, q)
        if len(p) >= 8 and s >= threshold:
            best = max(best, s)
    return best


_QUOTED_RE = re.compile(r'"([^"]{2,60})"')
_FIELD_PHRASES = tuple(load_intents().get("field_phrases", []))
# темы, которых нет ни в документе, ни в Положении (тогда поле ищем только по точному названию)
_FOREIGN_TOPICS = tuple(load_intents().get("foreign_topics", []))


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^\wё-]+", s) if t]


def _token_match(a: str, qt: list[str]) -> bool:
    """Есть ли синоним в вопросе (точно, по основе или с опечаткой)."""
    if len(a) <= 3:
        return a in qt
    stem = a[: max(4, len(a) - 2)]
    for t in qt:
        if t == a or t.startswith(stem) or (len(t) >= 4 and a.startswith(t[: max(4, len(t) - 2)])):
            return True
        if len(a) >= 6 and fuzz.ratio(a, t) >= 88:
            return True
    return False


def _name_score(name: str, q: str, qt: list[str]) -> float:
    n = name.lower().replace("ё", "е")
    if n in q:
        return 100.0
    toks = _tokens(n)
    if not toks:
        return 0.0
    if len(toks) == 1:
        return 90.0 if len(toks[0]) >= 4 and _token_match(toks[0], qt) else 0.0
    if all(_token_match(t, qt) for t in toks):
        return 92.0
    return 0.0


def _match_field(q: str, cfg: DocTypeConfig, threshold: int) -> tuple[Optional[FieldSpec], float]:
    """Ищет поле по кавычкам или синонимам."""
    quoted = _QUOTED_RE.findall(q)
    best: tuple[Optional[FieldSpec], float] = (None, 0.0)
    if quoted:
        target = quoted[0].strip().lower().replace("ё", "е")
        for spec in cfg.fields:
            for name in spec.search_names:
                s = fuzz.ratio(target, name.lower().replace("ё", "е"))
                if s > best[1]:
                    best = (spec, s)
        if best[1] >= threshold:
            return best
        best = (None, 0.0)
    qt = _tokens(q)
    foreign = any(t in q for t in _FOREIGN_TOPICS)
    for spec in cfg.fields:
        for name in spec.search_names:
            s = _name_score(name, q, qt)
            if s == 0.0:
                continue
            if foreign and s < 100.0:
                continue
            # длинные названия в приоритете (дата начала / дата окончания)
            s_adj = s + min(8, len(name) / 6)
            if s_adj > best[1]:
                best = (spec, s_adj)
    return best


def classify_question(question: str, cfg: DocTypeConfig) -> Intent:
    cfgq = get_settings().get("qa", {})
    thr = cfgq.get("field_match_threshold", 80)
    q = normalize_question(question)
    intents = load_intents()

    # 1. кто принимает решение
    s = _any_pattern(q, intents.get("decision", {}).get("patterns", []))
    if s >= 88:
        return Intent("decision", score=s)

    # 2. комплектность, но не вопрос про поле в кавычках
    quoted = _QUOTED_RE.findall(q)
    s_c = _any_pattern(q, intents.get("completeness", {}).get("patterns", []))
    if s_c >= 88 and not quoted:
        # "достаточно ли причины отпуска" это FAQ 4.4, проверяется ниже
        faq = _match_faq(q, intents.get("faq", []), cfg)
        if faq and faq[0].get("id") == "leave_reason_enough":
            return Intent("faq", faq=faq[0], score=faq[1])
        return Intent("completeness", score=s_c)

    # 2b. FAQ с точным совпадением важнее поля (например "проверяется ли подлинность подписи" это п. 2.3)
    faq_lit = _match_faq(q, intents.get("faq", []), cfg)
    if faq_lit and faq_lit[1] >= 100 and not quoted:
        return Intent("faq", faq=faq_lit[0], score=faq_lit[1])

    # 3. поле
    spec, s_f = _match_field(q, cfg, thr)
    if spec is not None and (quoted or any(p in q for p in _FIELD_PHRASES) or s_f >= thr):
        # вопрос про отметку, которой у типа нет (печать у заявления)
        return Intent("field", field_key=spec.key, score=s_f)
    # поле-отметка, отсутствующее у типа (печать у заявления)
    for mark, rule in cfg.not_required.items():
        words = {"seal": ["печат", "м.п."], "signature": ["подпис"]}.get(mark, [mark])
        if any(w in q for w in words):
            return Intent("faq", faq={"id": f"not_required_{mark}", "rule": rule, "value": "не требуется",
                                      "answer": None}, score=90)

    # 4. FAQ по Положению
    faq = _match_faq(q, intents.get("faq", []), cfg)
    if faq:
        return Intent("faq", faq=faq[0], score=faq[1])

    # 5. не установлено Положением
    for item in intents.get("not_established", []):
        s = _any_pattern(q, item.get("patterns", []), threshold=85)
        if s >= 85:
            return Intent("not_established", note=item, score=s)

    if s_c >= 88:  # комплектность с кавычками без найденного поля
        return Intent("completeness", score=s_c)
    return Intent("no_info", score=0.0)


def _match_faq(q: str, faq_items: list[dict], cfg: DocTypeConfig) -> Optional[tuple[dict, float]]:
    best: Optional[tuple[dict, float]] = None
    for item in faq_items:
        if item.get("doc_types") and cfg.key not in item["doc_types"]:
            continue
        s = _any_pattern(q, item.get("patterns", []), threshold=86)
        if s >= 86 and (best is None or s > best[1]):
            best = (item, s)
    return best
