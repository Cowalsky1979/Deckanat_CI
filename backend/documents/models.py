import uuid

from django.db import models


def upload_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:5]
    return f"uploads/{instance.id}/original.{ext}"


class Profile(models.Model):
    """Профиль кабинета (без входа: роль + имя; может быть привязан к Telegram id загрузок из бота)."""

    class Role(models.TextChoices):
        STUDENT = "student", "студент"
        DEAN = "dean", "деканат"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=16, choices=Role.choices)
    name = models.CharField(max_length=120)
    # null, а не пустая строка: unique допускает много NULL
    telegram_user_id = models.CharField(max_length=32, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"


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
    owner = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    # исправленная версия: ссылка на документ, который деканат вернул на доработку или отклонил
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions")
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


class DocumentReview(models.Model):
    """Заявка студента в деканат и решение по ней."""

    class Status(models.TextChoices):
        PENDING = "pending", "на рассмотрении"
        ACCEPTED = "accepted", "принято"
        REJECTED = "rejected", "отклонено"
        NEEDS_FIX = "needs_fix", "нужно исправить"

    class ReasonSource(models.TextChoices):
        AI = "ai", "причина от ИИ"
        MANUAL = "manual", "своя причина"

    document = models.OneToOneField(UploadedDocument, on_delete=models.CASCADE, related_name="review")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews")
    comment = models.TextField(blank=True)
    reason_source = models.CharField(max_length=8, choices=ReasonSource.choices, blank=True)
    seen_by_dean = models.BooleanField(default=False)   # для счетчика новых заявок

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "заявка в деканат"
        verbose_name_plural = "заявки в деканат"

    def __str__(self):
        return f"{self.document_id} {self.status}"


class Notification(models.Model):
    """Очередь сообщений для Telegram: бэкенд кладёт, бот забирает и отправляет."""

    telegram_user_id = models.CharField(max_length=32, db_index=True)
    document = models.ForeignKey(UploadedDocument, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32, blank=True)      # review_decided и т. п.
    text = models.TextField()                                # HTML для Telegram
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"

    def __str__(self):
        return f"{self.telegram_user_id} {self.kind} {'sent' if self.sent_at else 'pending'}"
