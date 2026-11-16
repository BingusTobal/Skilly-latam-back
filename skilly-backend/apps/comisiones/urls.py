from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminComisionesView,
    AdminResumenView,
    AdminTasaComisionViewSet,
    CotizarNetoView,
)

router = DefaultRouter()
router.register(
    r"admin/tasas-comision", AdminTasaComisionViewSet, basename="admin-tasa-comision"
)

urlpatterns = [
    path("tasa-neto/", CotizarNetoView.as_view(), name="tasa-neto"),
    path("admin/resumen/", AdminResumenView.as_view(), name="admin-resumen"),
    path("admin/comisiones/", AdminComisionesView.as_view(), name="admin-comisiones"),
    path("", include(router.urls)),
]
