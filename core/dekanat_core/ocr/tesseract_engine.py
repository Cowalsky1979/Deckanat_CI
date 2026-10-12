"""Tesseract (rus+eng), запасной движок."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import numpy as np

from ..models import OcrLine
from ..settings import get_settings
from .base import OcrEngine

log = logging.getLogger(__name__)

_DEFAULT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(self):
        self._ok: bool | None = None

    def _setup(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            import pytesseract  # type: ignore

            cfg = get_settings().get("ocr", {})
            cmd = cfg.get("tesseract_cmd") or os.environ.get("TESSERACT_CMD")
            if not cmd and not shutil.which("tesseract") and os.path.exists(_DEFAULT_WIN):
                cmd = _DEFAULT_WIN
            if cmd:
                pytesseract.pytesseract.tesseract_cmd = cmd
            tessdata = cfg.get("tessdata_dir")
            if tessdata and not os.environ.get("TESSDATA_PREFIX"):
                from ..settings import ROOT
                td = Path(tessdata)
                td = td if td.is_absolute() else ROOT / td
                if (td / "rus.traineddata").exists():
                    os.environ["TESSDATA_PREFIX"] = str(td)
            pytesseract.get_tesseract_version()
            self._ok = True
        except Exception as exc:  # pragma: no cover
            log.warning("Tesseract недоступен: %s", exc)
            self._ok = False
        return self._ok

    def available(self) -> bool:
        return self._setup()

    def recognize(self, rgb: np.ndarray) -> list[OcrLine]:
        if not self._setup():
            return []
        import pytesseract
        from pytesseract import Output

        lang = get_settings().get("ocr", {}).get("tesseract_lang", "rus+eng")
        try:
            data = pytesseract.image_to_data(rgb, lang=lang, config="--psm 6", output_type=Output.DICT)
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(rgb, lang="eng", config="--psm 6", output_type=Output.DICT)
        # собираем слова в строки
        groups: dict[tuple, list] = {}
        for i, word in enumerate(data["text"]):
            if not str(word).strip():
                continue
            conf = float(data["conf"][i])
            if conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append(
                (data["left"][i], data["top"][i], data["width"][i], data["height"][i], word, conf)
            )
        lines: list[OcrLine] = []
        for words in groups.values():
            words.sort(key=lambda w: w[0])
            x1 = min(w[0] for w in words)
            y1 = min(w[1] for w in words)
            x2 = max(w[0] + w[2] for w in words)
            y2 = max(w[1] + w[3] for w in words)
            text = " ".join(w[4] for w in words)
            conf = sum(w[5] for w in words) / len(words) / 100.0
            lines.append(OcrLine(text=text, bbox=(x1, y1, x2, y2), conf=conf, engine=self.name))
        return lines
