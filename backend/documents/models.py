import uuid

from django.db import models


def upload_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:5]
    return f"uploads/{instance.id}/original.{ext}"


class UploadedDocument(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "обрабатывается"
        DONE = "done", "готово"
        ERROR = "error", "ошибка"

    class Source(models.TextChoices):
        WEB = "web", "веб"
        TELEGRAM = "telegram", "Telegram"
        API = "api", "API"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=upload_path)
    original_name = models.CharField(max_length=255, blank=True)
    mime = models.CharField(max_length=64, blank=True)
    size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    selected_type = models.CharField(max_length=64, default="auto")       # что выбрал пользователь
    doc_type = models.CharField(max_length=64, blank=True)                 # итоговый тип
    type_confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROCESSING)
    error = models.TextField(blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.WEB)
    telegram_user_id = models.CharField(max_length=32, blank=True, db_index=True)
    timings = models.JSONField(default=dict, blank=True)
    pending_question = models.TextField(blank=True)      # вопрос, который пришел вместе с файлом
    pending_check = models.BooleanField(default=False)   # проверка без вопроса сразу после загрузки
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "загруженный документ"
        verbose_name_plural = "загруженные документы"

    def __str__(self):
        return f"{self.id} {self.doc_type or self.selected_type} {self.status}"


class ProcessingResult(models.Model):
    document = models.OneToOneField(UploadedDocument, on_delete=models.CASCADE, related_name="result")
    result = models.JSONField(default=dict)              # DocumentResult.to_dict()
    normalized_image = models.ImageField(upload_to="uploads/", blank=True)
    preview_image = models.ImageField(upload_to="uploads/", blank=True)          # маленький jpeg для просмотра
    original_preview = models.ImageField(upload_to="uploads/", blank=True)       # маленький jpeg исходника
    transform = models.JSONField(default=list, blank=True)  # матрица 3x3 из исходника в нормализованное
    original_size = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "результат обработки"
        verbose_name_plural = "результаты обработки"


class QuestionAnswer(models.Model):
    document = models.ForeignKey(UploadedDocument, on_delete=models.CASCADE, related_name="questions")
    question = models.TextField()
    answerable = models.BooleanField(default=False)
    value = models.TextField(null=True, blank=True)
    answer = models.TextField()
    sources = models.JSONField(default=list)
    intent = models.CharField(max_length=32, blank=True)
    field_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "вопрос-ответ"
        verbose_name_plural = "вопросы-ответы"
