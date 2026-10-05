"""
Rutas de autenticacion. Ticket 0.17.
Los endpoints de registro, perfil y moderacion se agregan en el Sprint 1
(tickets 1.6, 1.8, 1.9).
"""
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
