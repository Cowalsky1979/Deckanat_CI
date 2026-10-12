#!/usr/bin/env python
"""Диагностика OCR: сравнение распознанного текста с текстовым слоем PDF (только для отладки,
текстовый слой НЕ используется в предсказаниях).

  python scripts/ocr_diag.py --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from rapidfuzz import fuzz  # noqa: E402

from dekanat_core import pipeline  # noqa: E402


def pdf_text(path: Path) -> str:
    import fitz

    with fitz.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=30)
    args = p.parse_args()
    manifest = json.loads((ROOT / "data" / "documents.json").read_text(encoding="utf-8"))
    scores = []
    for m in manifest[: args.limit]:
        img = ROOT / "data" / m["image"]
        res, _ = pipeline.process_document(img.read_bytes(), img.name, m["document_type"])
        truth = pdf_text(ROOT / "data" / m["pdf"])
        s = fuzz.token_set_ratio(res.ocr_text, truth)
        scores.append(s)
        print(f"{m['document_id']}: сходство OCR с текстовым слоем {s:.1f}  ({res.quality.get('ocr', {}).get('engines')})")
    print(f"среднее: {sum(scores) / len(scores):.1f}")


if __name__ == "__main__":
    main()
