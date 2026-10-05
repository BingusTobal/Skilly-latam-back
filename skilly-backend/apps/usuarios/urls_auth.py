"""
Rutas de autenticacion y perfil. Tickets 0.17, 1.6 a 1.10, 1.14.

Se mantienen los endpoints de simplejwt (`token/`, `token/refresh/`) porque
son los que usan los tests del Sprint 0, y se agregan los de Sprint 1.
"""
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .views import (
    AdminListarOrganizacionesView,
    AdminListarProfesionalesView,
    CambiarPasswordView,
    HorarioDetailView,
    HorariosView,
    LoginView,
    MiPerfilProfesionalView,
    MiPerfilView,
    PasswordResetConfirmarView,
    PasswordResetView,
    RegistroOrganizacionView,
)

urlpatterns = [
    # --- Sprint 0 ---
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # --- Sprint 1 ---
    path(
        "registro-organizacion/",
        RegistroOrganizacionView.as_view(),
        name="registro_organizacion",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("me/", MiPerfilView.as_view(), name="mi_perfil"),
    path(
        "cambiar-password/", CambiarPasswordView.as_view(), name="cambiar_password"
    ),
    path("password-reset/", PasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/confirmar/",
        PasswordResetConfirmarView.as_view(),
        name="password_reset_confirmar",
    ),
    path(
        "mi-perfil-profesional/",
        MiPerfilProfesionalView.as_view(),
        name="mi_perfil_profesional",
    ),
    path("mis-horarios/", HorariosView.as_view(), name="mis_horarios"),
    path(
        "mis-horarios/<int:pk>/",
        HorarioDetailView.as_view(),
        name="mis_horarios_detail",
    ),
    # --- Panel admin (1.14) ---
    path(
        "admin/organizaciones/",
        AdminListarOrganizacionesView.as_view(),
        name="admin_organizaciones",
    ),
    path(
        "admin/profesionales/",
        AdminListarProfesionalesView.as_view(),
        name="admin_profesionales",
    ),
]