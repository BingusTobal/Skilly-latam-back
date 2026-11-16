"""
URLs raiz de Skilly Latam.
Ticket 0.14 expone GET /health; el resto de endpoints se agrega por sprint.
"""
from django.conf import settings
from django.conf.urls.static import static
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
    # Autenticacion JWT (0.17) y perfil/registro (Sprint 1)
    path("api/auth/", include("apps.usuarios.urls_auth")),
    # Postulaciones y certificados (Sprint 1)
    path("api/postulaciones/", include("apps.postulaciones.urls")),
    # Resumen y comisiones del panel admin (Sprint 5)
    path("api/", include("apps.comisiones.urls")),
    path("api/", include("apps.catalogo.urls")),
    # Pagos (Sprint 4): debe ir antes del router de reservas por la ruta anidada.
    path("api/", include("apps.pagos.urls")),
    # Reservas y disponibilidad (Sprint 3)
    path("api/", include("apps.reservas.urls")),
    # API por app (se va poblando sprint a sprint)
    path("api/", include("apps.usuarios.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)