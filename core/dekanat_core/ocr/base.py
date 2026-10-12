from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..models import OcrLine


class OcrEngine(ABC):
    name: str = "base"

    @abstractmethod
    def recognize(self, rgb: np.ndarray) -> list[OcrLine]:
        """Распознаёт текст, bbox в координатах этой картинки."""

    def available(self) -> bool:
        return True


def poly_to_bbox(poly) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
