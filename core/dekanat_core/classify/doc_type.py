"""Определение типа документа по тексту OCR."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..config.schema import DocTypeConfig, load_doc_types
from ..layout.lines import TextLine


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def score_type(cfg: DocTypeConfig, lines: list[TextLine]) -> float:
    texts = [_norm(l.text) for l in lines]
    top = texts[: max(5, len(texts) // 3)]  # заголовок обычно вверху
    title_score = 0.0
    for kw in cfg.detect.title_keywords:
        kwn = _norm(kw)
        for i, t in enumerate(texts):
            s = fuzz.partial_ratio(kwn, t)
            if s >= 85:
                bonus = 1.0 if i < len(top) else 0.6
                title_score = max(title_score, s / 100 * bonus * (0.6 + 0.4 * min(1, len(kwn) / 25)))
    label_hits = 0
    expected = [_norm(k) for k in cfg.detect.label_keywords] + [_norm(f.label) for f in cfg.fields]
    for kw in expected:
        if any(fuzz.partial_ratio(kw, t) >= 85 for t in texts):
            label_hits += 1
    label_score = label_hits / max(1, len(expected))
    return round(0.55 * title_score + 0.45 * label_score, 4)


def classify(lines: list[TextLine]) -> tuple[str, float, list[dict]]:
    """Возвращает (тип, уверенность 0..1, кандидаты)."""
    types = load_doc_types()
    scores = {k: score_type(cfg, lines) for k, cfg in types.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_key, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    # учитываем скор и отрыв от второго места
    conf = min(1.0, best * (0.5 + 0.5 * min(1.0, (best - second) / 0.25))) if best > 0 else 0.0
    return best_key, round(conf, 3), [{"key": k, "title": types[k].title, "score": s} for k, s in ranked]
