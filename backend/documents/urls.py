from django.urls import path

from . import views

urlpatterns = [
    path("health", views.HealthView.as_view()),
    path("doc-types", views.DocTypesView.as_view()),
    path("rules", views.RulesView.as_view()),
    path("documents", views.DocumentListCreateView.as_view()),
    path("documents/<uuid:pk>", views.DocumentDetailView.as_view()),
    path("documents/<uuid:pk>/ask", views.AskView.as_view()),
    path("documents/<uuid:pk>/fields/<str:key>", views.FieldUpdateView.as_view()),
    path("documents/<uuid:pk>/diff", views.DiffView.as_view()),
    path("documents/<uuid:pk>/check", views.CheckView.as_view()),
    path("documents/<uuid:pk>/ocr", views.OcrLinesView.as_view()),
    path("documents/<uuid:pk>/boxes", views.FieldBoxesView.as_view()),
    path("documents/<uuid:pk>/image", views.ImageView.as_view()),
    path("documents/<uuid:pk>/annotated.png", views.AnnotatedView.as_view()),
    path("documents/<uuid:pk>/fields/<str:key>/crop.png", views.CropView.as_view()),
    path("documents/<uuid:pk>/export.json", views.ExportView.as_view()),
    # кабинет
    path("profiles", views.ProfileView.as_view()),
    path("profiles/me", views.ProfileMeView.as_view()),
    path("documents/<uuid:pk>/submit", views.SubmitReviewView.as_view()),
    path("documents/<uuid:pk>/review/seen", views.ReviewSeenView.as_view()),
    path("documents/<uuid:pk>/review/decide", views.ReviewDecideView.as_view()),
    path("reviews/summary", views.ReviewSummaryView.as_view()),
    path("reviews/export.csv", views.ReviewsCsvView.as_view()),
    # очередь уведомлений для Telegram-бота
    path("notifications/pending", views.NotificationsPendingView.as_view()),
    path("notifications/<int:pk>/sent", views.NotificationSentView.as_view()),
]
