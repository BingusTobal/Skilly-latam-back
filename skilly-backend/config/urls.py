"""
URLs raiz de Skilly Latam.
Ticket 0.14 expone GET /health; el resto de endpoints se agrega por sprint.
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.vistas import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    # 0.14 health check
    path("health/", health_check, name="health"),
    # Esquema OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Autenticacion JWT (0.17)
    path("api/auth/", include("apps.usuarios.urls_auth")),
    # API por app (se va poblando sprint a sprint)
    path("api/", include("apps.usuarios.urls")),
]