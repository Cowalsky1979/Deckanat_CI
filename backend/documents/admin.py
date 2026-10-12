from django.contrib import admin

from .models import ProcessingResult, QuestionAnswer, UploadedDocument


class QAInline(admin.TabularInline):
    model = QuestionAnswer
    extra = 0
    readonly_fields = ["question", "answerable", "value", "answer", "sources", "intent", "created_at"]


@admin.register(UploadedDocument)
class UploadedDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "original_name", "doc_type", "type_confidence", "status", "source", "created_at"]
    list_filter = ["doc_type", "status", "source"]
    search_fields = ["original_name", "id"]
    readonly_fields = ["id", "sha256", "timings", "created_at"]
    inlines = [QAInline]


@admin.register(ProcessingResult)
class ProcessingResultAdmin(admin.ModelAdmin):
    list_display = ["document", "updated_at"]
    readonly_fields = ["result", "transform", "original_size"]
