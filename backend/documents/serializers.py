from rest_framework import serializers

from .models import QuestionAnswer, UploadedDocument


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


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)


class ChangeTypeSerializer(serializers.Serializer):
    doc_type = serializers.CharField(max_length=64)


class DocumentSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()
    questions = QuestionAnswerSerializer(many=True, read_only=True)
    images = serializers.SerializerMethodField()

    class Meta:
        model = UploadedDocument
        fields = ["id", "original_name", "mime", "size", "selected_type", "doc_type", "type_confidence",
                  "status", "error", "source", "timings", "pending_question", "pending_check", "created_at",
                  "result", "questions", "images"]

    def get_result(self, obj):
        if obj.status != UploadedDocument.Status.DONE or not hasattr(obj, "result"):
            return None
        r = dict(obj.result.result)
        r.pop("ocr_lines", None)  # много данных, есть отдельный эндпоинт /ocr
        r["transform"] = obj.result.transform
        r["original_size"] = obj.result.original_size
        return r

    def get_images(self, obj):
        request = self.context.get("request")
        base = request.build_absolute_uri("/")[:-1] if request else ""
        return {
            "original": f"{base}/api/v1/documents/{obj.id}/image?variant=original",
            "original_preview": f"{base}/api/v1/documents/{obj.id}/image?variant=original_preview",
            "normalized": f"{base}/api/v1/documents/{obj.id}/image?variant=normalized",
            "preview": f"{base}/api/v1/documents/{obj.id}/image?variant=preview",
            "annotated": f"{base}/api/v1/documents/{obj.id}/annotated.png",
        }
