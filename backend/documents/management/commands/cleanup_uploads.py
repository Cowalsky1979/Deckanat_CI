"""Удаление загруженных документов старше N дней (по умолчанию 1)."""
import shutil
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from documents.models import UploadedDocument


class Command(BaseCommand):
    help = "Удалить загрузки старше --days дней"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=1.0)

    def handle(self, *args, **opts):
        border = timezone.now() - timedelta(days=opts["days"])
        qs = UploadedDocument.objects.filter(created_at__lt=border)
        n = 0
        for doc in qs:
            shutil.rmtree(settings.MEDIA_ROOT / "uploads" / str(doc.id), ignore_errors=True)
            doc.delete()
            n += 1
        self.stdout.write(f"Удалено документов: {n}")
