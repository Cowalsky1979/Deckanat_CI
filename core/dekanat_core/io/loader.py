"""Загрузка входного файла (JPG/PNG/одностраничный PDF) в массив RGB."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
from PIL import Image, ImageOps

from ..settings import get_settings

Image.MAX_IMAGE_PIXELS = 80_000_000  # защита от слишком больших картинок


class UnsupportedFileError(ValueError):
    pass


class MultiPageError(ValueError):
    pass


@dataclass
class LoadedImage:
    rgb: np.ndarray
    source_format: str          # png | jpeg | pdf
    pages: int = 1
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def sniff_format(data: bytes) -> Optional[str]:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] in (b"RIFF",) and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] in (b"BM",):
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def load_bytes(data: bytes, filename: str = "", *, first_page_only: bool = False) -> LoadedImage:
    settings = get_settings()
    max_mb = settings.get("io", {}).get("max_file_mb", 20)
    if len(data) > max_mb * 1024 * 1024:
        raise UnsupportedFileError(f"Файл больше {max_mb} МБ")
    fmt = sniff_format(data)
    if fmt is None:
        raise UnsupportedFileError("Поддерживаются JPG, PNG и одностраничный PDF")
    if fmt == "pdf":
        return _load_pdf(data, first_page_only=first_page_only)
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as exc:
        raise UnsupportedFileError(f"Не удалось прочитать изображение: {exc}") from exc
    return LoadedImage(rgb=np.asarray(img), source_format=fmt)


def _load_pdf(data: bytes, *, first_page_only: bool) -> LoadedImage:
    import fitz  # PyMuPDF

    dpi = get_settings().get("io", {}).get("pdf_dpi", 200)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnsupportedFileError(f"Не удалось открыть PDF: {exc}") from exc
    warnings: list[str] = []
    if doc.page_count != 1:
        if not first_page_only:
            raise MultiPageError(
                f"PDF содержит {doc.page_count} стр.; поддерживается одностраничный PDF "
                "(загрузите нужную страницу отдельно)"
            )
        warnings.append(f"PDF содержит {doc.page_count} стр.; обработана только первая")
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        arr = arr[:, :, :3]
    return LoadedImage(rgb=np.ascontiguousarray(arr), source_format="pdf", pages=doc.page_count, warnings=warnings)


def load_file(path: Union[str, Path], **kw) -> LoadedImage:
    p = Path(path)
    return load_bytes(p.read_bytes(), p.name, **kw)
