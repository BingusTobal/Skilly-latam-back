from django.urls import path

from .views import EstadoPagoView, IniciarPagoView, RetornoPagoView

urlpatterns = [
    path(
        "reservas/<int:pk>/pago/iniciar/",
        IniciarPagoView.as_view(),
        name="pago-iniciar",
    ),
    path(
        "pagos/transbank/retorno/",
        RetornoPagoView.as_view(),
        name="pago-retorno",
    ),
    path(
        "pagos/<uuid:referencia>/estado/",
        EstadoPagoView.as_view(),
        name="pago-estado",
    ),
]
