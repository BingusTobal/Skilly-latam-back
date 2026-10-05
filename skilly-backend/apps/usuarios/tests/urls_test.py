"""URLs de prueba.

Replica el enrutado real de la API (config/urls.py) mas un endpoint minimo que
exige autenticacion, para poder probar el permiso por defecto sin depender de
los endpoints que cada sprint agrega.
"""
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def endpoint_protegido(request):
    return Response({"ok": True})


urlpatterns = [
    path("api/auth/", include("apps.usuarios.urls_auth")),
    path("protegido/", endpoint_protegido, name="endpoint_protegido"),
]