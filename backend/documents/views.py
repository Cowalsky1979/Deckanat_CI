from __future__ import annotations

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from dekanat_core.rules.positions import load_positions

from . import services
from .identity import HEADER, current_profile, require_profile
from .models import DocumentReview, Profile, UploadedDocument
from .serializers import (AskSerializer, ChangeTypeSerializer, DecideSerializer, DocumentListSerializer,
                          DocumentSerializer, ProfileCreateSerializer, ProfileSerializer, QuestionAnswerSerializer,
                          ReviewSerializer, UploadSerializer)


def _doc(pk) -> UploadedDocument:
    return get_object_or_404(UploadedDocument.objects.select_related("result", "owner", "review", "review__reviewer"), pk=pk)


class HealthView(APIView):
    def get(self, request):
        from dekanat_core.ocr import ensemble
        from dekanat_core.settings import get_settings

        cfg = get_settings().get("ocr", {})
        engines = {}
        for name in (cfg.get("primary"), cfg.get("fallback")):
            if not name:
                continue
            eng = ensemble.get_engine(name)
            loaded = getattr(eng, "_det", None) is not None or getattr(eng, "_ok", None) is True
            engines[name] = "ready" if loaded else "not_loaded"
        return Response({"status": "ok", "engines": engines, "doc_types": [t["key"] for t in services.doc_types_public()]})


class DocTypesView(APIView):
    def get(self, request):
        return Response(services.doc_types_public())


class RulesView(APIView):
    def get(self, request):
        return Response(load_positions().to_dict())


class DocumentListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses=DocumentListSerializer(many=True))
    def get(self, request):
        """Список для кабинета: студент видит свои документы, деканат - заявки (?review=pending|decided|all)."""
        profile = require_profile(request)
        qs = UploadedDocument.objects.select_related("result", "owner", "review", "review__reviewer").prefetch_related("questions")
        if profile.role == Profile.Role.DEAN:
            mode = request.GET.get("review", "pending")
            if mode == "pending":
                qs = qs.filter(review__status=DocumentReview.Status.PENDING).order_by("review__submitted_at")
            elif mode == "decided":
                qs = qs.filter(review__isnull=False).exclude(review__status=DocumentReview.Status.PENDING).order_by("-review__decided_at")
            else:
                qs = qs.filter(review__isnull=False).order_by("-review__submitted_at")
        else:
            qs = qs.filter(owner=profile)
        try:
            limit = max(1, min(int(request.GET.get("limit", 100)), 500))
        except ValueError:
            limit = 100
        return Response(DocumentListSerializer(qs[:limit], many=True, context={"request": request}).data)

    @extend_schema(request=UploadSerializer, responses=DocumentSerializer)
    def post(self, request):
        ser = UploadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        f = ser.validated_data["file"]
        data = f.read()
        q = (ser.validated_data.get("question") or "").strip()
        check = bool(ser.validated_data.get("check"))
        # async=1: сразу отдаем 202, обработка идет в фоне (нужно для туннеля)
        wait = str(request.data.get("async", "")).lower() not in ("1", "true", "yes")
        tg_id = ser.validated_data.get("telegram_user_id", "")
        owner = services.owner_for(request.headers.get(HEADER), tg_id)
        try:
            doc = services.process_upload(data, f.name, ser.validated_data.get("doc_type") or "auto",
                                          source=ser.validated_data.get("source", "web"),
                                          telegram_user_id=tg_id, owner=owner,
                                          question=q, check=check, wait=wait)
        except services.ProcessingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if not wait:
            payload = DocumentSerializer(doc, context={"request": request}).data
            payload["answer"] = None
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        doc = _doc(doc.pk)
        payload = DocumentSerializer(doc, context={"request": request}).data
        last = doc.questions.order_by("-created_at").first() if (q or check) else None
        payload["answer"] = QuestionAnswerSerializer(last).data if last else None
        return Response(payload, status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, pk):
        return Response(DocumentSerializer(_doc(pk), context={"request": request}).data)

    @extend_schema(request=ChangeTypeSerializer, responses=DocumentSerializer)
    def patch(self, request, pk):
        doc = _doc(pk)
        ser = ChangeTypeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.change_type(doc, ser.validated_data["doc_type"])
        except KeyError as exc:
            return Response({"detail": str(exc.args[0])}, status=400)
        return Response(DocumentSerializer(_doc(pk), context={"request": request}).data)

    def delete(self, request, pk):
        doc = _doc(pk)
        doc.delete()
        return Response(status=204)


class AskView(APIView):
    parser_classes = [JSONParser, FormParser]

    @extend_schema(request=AskSerializer, responses=QuestionAnswerSerializer)
    def post(self, request, pk):
        doc = _doc(pk)
        if doc.status != UploadedDocument.Status.DONE:
            return Response({"detail": "Документ не обработан"}, status=409)
        ser = AskSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        qa = services.ask(doc, ser.validated_data["question"].strip())
        return Response(QuestionAnswerSerializer(qa).data)


class CheckView(APIView):
    def post(self, request, pk):
        doc = _doc(pk)
        if doc.status != UploadedDocument.Status.DONE:
            return Response({"detail": "Документ не обработан"}, status=409)
        return Response(QuestionAnswerSerializer(services.check(doc)).data)


# ---------- кабинет: профили и заявки ----------

class ProfileView(APIView):
    parser_classes = [JSONParser, FormParser]

    @extend_schema(request=ProfileCreateSerializer, responses=ProfileSerializer)
    def post(self, request):
        ser = ProfileCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        profile, created = services.find_or_create_profile(d["role"], d["name"], d["telegram_user_id"])
        return Response(ProfileSerializer(profile).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ProfileMeView(APIView):
    def get(self, request):
        profile = current_profile(request)
        if profile is None:
            return Response({"detail": "Профиль не найден"}, status=404)
        return Response(ProfileSerializer(profile).data)


class SubmitReviewView(APIView):
    @extend_schema(responses=ReviewSerializer)
    def post(self, request, pk):
        profile = require_profile(request, Profile.Role.STUDENT)
        doc = _doc(pk)
        if doc.owner_id is not None and doc.owner_id != profile.id:
            return Response({"detail": "Это документ другого студента"}, status=403)
        try:
            review = services.submit_for_review(doc, profile)
        except services.ReviewError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ReviewSummaryView(APIView):
    def get(self, request):
        require_profile(request, Profile.Role.DEAN)
        pending = DocumentReview.objects.filter(status=DocumentReview.Status.PENDING)
        return Response({"pending": pending.count(), "unseen": pending.filter(seen_by_dean=False).count()})


def _review(pk) -> DocumentReview:
    return get_object_or_404(DocumentReview.objects.select_related("document", "reviewer"), document_id=pk)


class ReviewSeenView(APIView):
    def post(self, request, pk):
        require_profile(request, Profile.Role.DEAN)
        review = _review(pk)
        if not review.seen_by_dean:
            review.seen_by_dean = True
            review.save(update_fields=["seen_by_dean"])
        return Response(ReviewSerializer(review).data)


class ReviewDecideView(APIView):
    parser_classes = [JSONParser, FormParser]

    @extend_schema(request=DecideSerializer, responses=DocumentSerializer)
    def post(self, request, pk):
        profile = require_profile(request, Profile.Role.DEAN)
        review = _review(pk)
        ser = DecideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.decide(review, profile, **ser.validated_data)
        return Response(DocumentSerializer(_doc(pk), context={"request": request}).data)


class OcrLinesView(APIView):
    def get(self, request, pk):
        doc = _doc(pk)
        return Response({"ocr_text": doc.result.result.get("ocr_text", ""),
                         "ocr_lines": doc.result.result.get("ocr_lines", [])})


class FieldBoxesView(APIView):
    def get(self, request, pk):
        return Response(services.field_boxes(_doc(pk)))


IMMUTABLE = "public, max-age=31536000, immutable"


class ImageView(View):
    def get(self, request, pk):
        doc = _doc(pk)
        variant = request.GET.get("variant", "preview")
        if variant == "original":
            resp = FileResponse(doc.file.open("rb"), content_type=doc.mime or "application/octet-stream")
        else:
            if not hasattr(doc, "result") or not doc.result.normalized_image:
                raise Http404
            if variant == "normalized":
                resp = FileResponse(doc.result.normalized_image.open("rb"), content_type="image/png")
            else:
                services.ensure_previews(doc)
                f = doc.result.original_preview if variant == "original_preview" else doc.result.preview_image
                resp = FileResponse(f.open("rb"), content_type="image/jpeg")
        resp["Cache-Control"] = IMMUTABLE
        return resp


class AnnotatedView(View):
    def get(self, request, pk):
        doc = _doc(pk)
        if doc.status != UploadedDocument.Status.DONE:
            raise Http404
        resp = HttpResponse(services.annotated_png(doc, request.GET.get("field")), content_type="image/jpeg")
        resp["Cache-Control"] = IMMUTABLE
        return resp


class CropView(View):
    def get(self, request, pk, key):
        doc = _doc(pk)
        data = services.crop_png(doc, key)
        if data is None:
            raise Http404("Для этого поля нет координат")
        resp = HttpResponse(data, content_type="image/jpeg")
        resp["Cache-Control"] = IMMUTABLE
        return resp


class ExportView(APIView):
    def get(self, request, pk):
        import json as _json

        data = services.export_json(_doc(pk))
        resp = HttpResponse(_json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
        if request.GET.get("download"):
            resp["Content-Disposition"] = 'attachment; filename="%s.json"' % pk
        return resp


class SpaView(View):
    """Отдает index.html фронта."""

    def get(self, request, *args, **kwargs):
        index = settings.FRONTEND_DIST / "index.html"
        if not index.exists():
            return HttpResponse(
                "<h1>Онлайн-деканат</h1><p>Фронтенд не собран. Выполните <code>cd frontend && npm install && npm run build</code> "
                "или откройте dev-сервер Vite (http://localhost:5173). API: <a href='/api/docs/'>/api/docs/</a></p>",
                content_type="text/html; charset=utf-8",
            )
        return HttpResponse(index.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
