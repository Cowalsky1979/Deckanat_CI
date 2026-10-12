from django.contrib import admin

from .models import DocumentReview, ProcessingResult, Profile, QuestionAnswer, UploadedDocument


class QAInline(admin.TabularInline):
    model = QuestionAnswer
    extra = 0
    readonly_fields = ["question", "answerable", "value", "answer", "sources", "intent", "created_at"]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "role", "telegram_user_id", "created_at"]
    list_filter = ["role"]
    search_fields = ["name", "telegram_user_id"]


@admin.register(UploadedDocument)
class UploadedDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "original_name", "doc_type", "type_confidence", "status", "source", "owner", "created_at"]
    list_filter = ["doc_type", "status", "source"]
    search_fields = ["original_name", "id"]
    readonly_fields = ["id", "sha256", "timings", "created_at"]
    inlines = [QAInline]


@admin.register(DocumentReview)
class DocumentReviewAdmin(admin.ModelAdmin):
    list_display = ["document", "status", "reviewer", "submitted_at", "decided_at", "seen_by_dean"]
    list_filter = ["status", "seen_by_dean"]


@admin.register(ProcessingResult)
class ProcessingResultAdmin(admin.ModelAdmin):
    list_display = ["document", "updated_at"]
    readonly_fields = ["result", "transform", "original_size"]
