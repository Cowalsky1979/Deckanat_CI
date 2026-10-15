from rest_framework import serializers

from . import services
from .models import DocumentReview, Notification, Profile, QuestionAnswer, UploadedDocument


class QuestionAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionAnswer
        fields = ["id", "question", "answerable", "value", "answer", "sources", "intent", "field_key", "created_at"]


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    doc_type = serializers.CharField(required=False, default="auto", allow_blank=True)
    question = serializers.CharField(required=False, allow_blank=True, default="")
    check = serializers.BooleanField(required=False, default=False)
    source = serializers.ChoiceField(choices=["web", "telegram", "api"], required=False, default="web")
    telegram_user_id = serializers.CharField(required=False, allow_blank=True, default="")
    parent = serializers.UUIDField(required=False, allow_null=True, default=None)   # исправленная версия документа


class FieldUpdateSerializer(serializers.Serializer):
    """Ручная правка значения поля; пустая строка возвращает значение OCR."""

    value = serializers.CharField(max_length=500, allow_blank=True)


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)


class ChangeTypeSerializer(serializers.Serializer):
    doc_type = serializers.CharField(max_length=64)


# ---------- кабинет ----------

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["id", "role", "name", "telegram_user_id", "created_at"]


class ProfileShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["id", "role", "name"]


class ProfileCreateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Profile.Role.choices)
    name = serializers.CharField(max_length=120)
    telegram_user_id = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")

    def validate_name(self, v):
        v = v.strip()
        if not v:
            raise serializers.ValidationError("Укажите имя")
        return v

    def validate_telegram_user_id(self, v):
        return v.strip() or None  # unique: пустое значение храним как NULL


class ReviewSerializer(serializers.ModelSerializer):
    reviewer = ProfileShortSerializer(read_only=True)

    class Meta:
        model = DocumentReview
        fields = ["id", "status", "submitted_at", "decided_at", "reviewer", "comment", "reason_source", "seen_by_dean"]


class DecideSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[DocumentReview.Status.ACCEPTED, DocumentReview.Status.REJECTED,
                                              DocumentReview.Status.NEEDS_FIX])
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    reason_source = serializers.ChoiceField(choices=DocumentReview.ReasonSource.choices, required=False,
                                            allow_blank=True, default="")

    def validate(self, data):
        if data["status"] != DocumentReview.Status.ACCEPTED and not data.get("comment", "").strip():
            raise serializers.ValidationError({"comment": "Укажите причину: что нужно исправить"})
        return data


class NotificationSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "telegram_user_id", "document_id", "kind", "text", "created_at"]


class RevisionShortSerializer(serializers.ModelSerializer):
    """Ссылка на другую версию документа (родитель или исправление)."""

    review_status = serializers.SerializerMethodField()
    review_comment = serializers.SerializerMethodField()
    doc_type_title = serializers.SerializerMethodField()

    class Meta:
        model = UploadedDocument
        fields = ["id", "original_name", "doc_type", "doc_type_title", "status", "created_at", "review_status", "review_comment"]

    def get_review_status(self, obj):
        return obj.review.status if hasattr(obj, "review") else None

    def get_review_comment(self, obj):
        return obj.review.comment if hasattr(obj, "review") else ""

    def get_doc_type_title(self, obj):
        if obj.status == UploadedDocument.Status.DONE and hasattr(obj, "result"):
            return obj.result.result.get("doc_type_title") or obj.doc_type
        return obj.doc_type


class _ReviewMixin(serializers.Serializer):
    owner = ProfileShortSerializer(read_only=True)
    review = serializers.SerializerMethodField()
    ai_summary = serializers.SerializerMethodField()
    parent = RevisionShortSerializer(read_only=True)
    revisions = serializers.SerializerMethodField()

    def get_review(self, obj):
        return ReviewSerializer(obj.review).data if hasattr(obj, "review") else None

    def get_ai_summary(self, obj):
        return services.review_summary(obj)

    def get_revisions(self, obj):
        # revisions.all() использует prefetch_related из списка, в карточке это один запрос
        rows = sorted(obj.revisions.all(), key=lambda d: d.created_at)
        return RevisionShortSerializer(rows, many=True).data


class DocumentSerializer(_ReviewMixin, serializers.ModelSerializer):
    result = serializers.SerializerMethodField()
    questions = QuestionAnswerSerializer(many=True, read_only=True)
    images = serializers.SerializerMethodField()

    class Meta:
        model = UploadedDocument
        fields = ["id", "original_name", "mime", "size", "selected_type", "doc_type", "type_confidence",
                  "status", "error", "source", "timings", "pending_question", "pending_check", "created_at",
                  "result", "questions", "images", "owner", "review", "ai_summary", "parent", "revisions"]

    def get_result(self, obj):
        if obj.status != UploadedDocument.Status.DONE or not hasattr(obj, "result"):
            return None
        r = dict(obj.result.result)
        r.pop("ocr_lines", None)  # много данных, есть отдельный эндпоинт /ocr
        r["transform"] = obj.result.transform
        r["original_size"] = obj.result.original_size
        return r

    def get_images(self, obj):
        # относительные пути: за HTTPS-туннелем бэкенд видит http, и абсолютные ссылки блокируются как mixed content
        base = f"/api/v1/documents/{obj.id}"
        return {
            "original": f"{base}/image?variant=original",
            "original_preview": f"{base}/image?variant=original_preview",
            "normalized": f"{base}/image?variant=normalized",
            "preview": f"{base}/image?variant=preview",
            "annotated": f"{base}/annotated.png",
        }


class DocumentListSerializer(_ReviewMixin, serializers.ModelSerializer):
    """Компактная строка для списков кабинета, без полного результата OCR."""

    doc_type_title = serializers.SerializerMethodField()
    validation_status = serializers.SerializerMethodField()
    missing_count = serializers.SerializerMethodField()
    questions_count = serializers.SerializerMethodField()
    last_answer = serializers.SerializerMethodField()

    class Meta:
        model = UploadedDocument
        fields = ["id", "original_name", "doc_type", "doc_type_title", "status", "error", "source", "created_at",
                  "validation_status", "missing_count", "questions_count", "last_answer", "owner", "review", "ai_summary",
                  "parent", "revisions"]

    def _result(self, obj) -> dict:
        return obj.result.result if obj.status == UploadedDocument.Status.DONE and hasattr(obj, "result") else {}

    def get_doc_type_title(self, obj):
        return self._result(obj).get("doc_type_title") or obj.doc_type

    def get_validation_status(self, obj):
        return (self._result(obj).get("validation") or {}).get("status")

    def get_missing_count(self, obj):
        return len((self._result(obj).get("validation") or {}).get("missing_fields") or [])

    def get_questions_count(self, obj):
        return len(obj.questions.all())

    def get_last_answer(self, obj):
        qs = list(obj.questions.all())
        return qs[-1].answer[:200] if qs else None
