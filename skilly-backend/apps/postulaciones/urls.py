"""
Rutas de postulaciones y certificados. Tickets 1.8, 1.11.

Las rutas de administración cuelgan del router de DRF, pero se montan bajo
`/api/postulaciones/admin/...` para que quede claro que son del panel interno
y no de la API pública de la organización.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminCertificadoViewSet,
    AdminPostulacionViewSet,
    CertificadosPostulacionView,
    CrearPostulacionView,
    MiPostulacionView,
    ReenviarPostulacionView,
)

router = DefaultRouter()
router.register(r"admin/postulaciones", AdminPostulacionViewSet, basename="admin-postulacion")
router.register(r"admin/certificados", AdminCertificadoViewSet, basename="admin-certificado")

urlpatterns = [
    # --- Público ---
    path("", CrearPostulacionView.as_view(), name="crear_postulacion"),
    # --- Profesional ---
    path("mias/", MiPostulacionView.as_view(), name="mi_postulacion"),
    path(
        "<int:pk>/reenviar/",
        ReenviarPostulacionView.as_view(),
        name="reenviar_postulacion",
    ),
    path(
        "<int:pk>/certificados/",
        CertificadosPostulacionView.as_view(),
        name="certificados_postulacion",
    ),
    # --- Panel admin ---
    path("", include(router.urls)),
]