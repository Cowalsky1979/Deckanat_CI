"""Полная очистка пользовательских данных: документы, результаты, вопросы, заявки, уведомления, профили и файлы загрузок.

  python manage.py reset_data --yes

Таблицы и миграции остаются, это не `docker compose down -v`. Удобно перед демо или сдачей.
"""
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from documents.models import DocumentReview, Notification, ProcessingResult, Profile, QuestionAnswer, UploadedDocument


class Command(BaseCommand):
    help = "Удалить все документы, заявки, профили и файлы загрузок"

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="подтвердить удаление без вопроса")
        parser.add_argument("--keep-profiles", action="store_true", help="оставить профили кабинета")

    def handle(self, *args, **opts):
        counts = {
            "документов": UploadedDocument.objects.count(),
            "результатов": ProcessingResult.objects.count(),
            "вопросов": QuestionAnswer.objects.count(),
            "заявок": DocumentReview.objects.count(),
            "уведомлений": Notification.objects.count(),
            "профилей": 0 if opts["keep_profiles"] else Profile.objects.count(),
        }
        summary = ", ".join(f"{v} {k}" for k, v in counts.items())
        if not opts["yes"]:
            raise CommandError(f"Будет удалено: {summary}. Повторите с --yes, чтобы подтвердить.")
        # документы каскадом удаляют результаты, вопросы, заявки и уведомления
        UploadedDocument.objects.all().delete()
        Notification.objects.all().delete()
        if not opts["keep_profiles"]:
            Profile.objects.all().delete()
        uploads = settings.MEDIA_ROOT / "uploads"
        if uploads.exists():
            shutil.rmtree(uploads, ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(f"Удалено: {summary}; папка {uploads} очищена"))
