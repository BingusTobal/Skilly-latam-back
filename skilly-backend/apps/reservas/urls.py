from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ReservaViewSet,
    ServicioDisponibilidadView,
    ServicioSlotsView,
)

router = DefaultRouter()
router.register(r"reservas", ReservaViewSet, basename="reserva")

urlpatterns = [
    path("servicios/<int:pk>/slots/", ServicioSlotsView.as_view(), name="servicio-slots"),
    path(
        "servicios/<int:pk>/disponibilidad/",
        ServicioDisponibilidadView.as_view(),
        name="servicio-disponibilidad",
    ),
    path("", include(router.urls)),
]
