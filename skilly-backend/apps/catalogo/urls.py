from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminServiciosViewSet,
    CategoriaViewSet,
    MisServiciosViewSet,
    ServicioPublicoViewSet,
)

router = DefaultRouter()
router.register(r"servicios", ServicioPublicoViewSet, basename="catalogo-servicio")
router.register(r"categorias", CategoriaViewSet, basename="catalogo-categoria")
router.register(r"profesional/servicios", MisServiciosViewSet, basename="profesional-servicio")
router.register(r"admin/servicios", AdminServiciosViewSet, basename="admin-servicio")

urlpatterns = [
    path("", include(router.urls)),
]