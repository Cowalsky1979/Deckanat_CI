import logging
import os
import sys
import threading

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger(__name__)


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    verbose_name = "Документы"

    def ready(self):
        # грузим OCR-модели в фоне, иначе первый запрос долго ждет
        if not settings.DEKANAT_WARMUP or "test" in sys.argv or os.environ.get("RUN_MAIN") == "false":
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return  # это родительский процесс автоперезагрузки

        def _warm():
            try:
                from dekanat_core.ocr import ensemble
                from dekanat_core.settings import get_settings

                name = get_settings().get("ocr", {}).get("primary", "paddle")
                ok = ensemble.get_engine(name).available()
                log.info("OCR-движок %s %s", name, "готов" if ok else "недоступен")
            except Exception as exc:  # pragma: no cover
                log.warning("Прогрев OCR не удался: %s", exc)

        threading.Thread(target=_warm, name="ocr-warmup", daemon=True).start()
