from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from documents.views import SpaView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("documents.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# собранный фронт (frontend/dist) отдает сам Django, чтобы всё было на одном порту
urlpatterns += [re_path(r"^(?!api/|admin/|media/|static/|assets/).*$", SpaView.as_view(), name="spa")]
