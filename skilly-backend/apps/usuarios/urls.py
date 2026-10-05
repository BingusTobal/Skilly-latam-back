"""
Rutas de la API de usuarios.

Lo que se usa de verdad vive en `urls_auth.py` (auth, perfil y panel admin).
Este módulo queda para las rutas que no sean de autenticación; hoy está vacío a
propósito, porque el Sprint 1 no define ningún endpoint de usuario fuera de
`/api/auth/`.
"""
from django.urls import path

app_name = "usuarios"

urlpatterns: list = []