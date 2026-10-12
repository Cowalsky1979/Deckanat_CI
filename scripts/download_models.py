#!/usr/bin/env python
"""Скачивает веса OCR (PaddleOCR и tessdata rus/eng), чтобы работать без интернета.

  python scripts/download_models.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"


def download_tessdata():
    d = ROOT / "models" / "tessdata"
    d.mkdir(parents=True, exist_ok=True)
    for lang in ("rus", "eng"):
        dst = d / f"{lang}.traineddata"
        if dst.exists():
            print(f"[tesseract] {lang}: уже есть")
            continue
        print(f"[tesseract] скачиваю {lang}...")
        urllib.request.urlretrieve(TESSDATA_URL.format(lang=lang), dst)
    print(f"[tesseract] tessdata: {d}")


def download_paddle():
    from dekanat_core.ocr.paddle_engine import PaddleEngine

    eng = PaddleEngine()
    print("[paddle] загрузка моделей (скачиваются при первом запуске)...")
    print("[paddle] готово" if eng.available() else "[paddle] НЕ УДАЛОСЬ (см. лог)")
    from dekanat_core.preprocess.orientation import _load_model

    print("[paddle] классификатор ориентации:", "готово" if _load_model() is not None else "НЕ УДАЛОСЬ")


if __name__ == "__main__":
    download_tessdata()
    download_paddle()
