from django.urls import path

from .views import AdminComisionesView, AdminResumenView

urlpatterns = [
    path("admin/resumen/", AdminResumenView.as_view(), name="admin-resumen"),
    path("admin/comisiones/", AdminComisionesView.as_view(), name="admin-comisiones"),
]
