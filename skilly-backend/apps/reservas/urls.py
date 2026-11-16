from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminDisputaResolverView,
    AdminDisputasView,
    DisputaViewSet,
    ReservaViewSet,
    ServicioDisponibilidadView,
    ServicioSlotsView,
)

router = DefaultRouter()
router.register(r"reservas", ReservaViewSet, basename="reserva")
router.register(r"disputas", DisputaViewSet, basename="disputa")

urlpatterns = [
    path("admin/disputas/", AdminDisputasView.as_view(), name="admin-disputas"),
    path(
        "admin/disputas/<int:pk>/resolver/",
        AdminDisputaResolverView.as_view(),
        name="admin-disputa-resolver",
    ),
    path("servicios/<int:pk>/slots/", ServicioSlotsView.as_view(), name="servicio-slots"),
    path(
        "servicios/<int:pk>/disponibilidad/",
        ServicioDisponibilidadView.as_view(),
        name="servicio-disponibilidad",
    ),
    path("", include(router.urls)),
]
