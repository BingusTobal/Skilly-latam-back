"""
Vistas de usuarios: registro de organización, login, perfil, password reset
y gestión de horarios. Tickets 1.6 a 1.10, 1.14.

Dos decisiones de arquitectura que atraviesan este archivo:

  1. El login es por EMAIL, no por username (0.17). `simplejwt` autentica con
     USERNAME_FIELD, así que alcanza con ponerlo en el serializer y no tocar
     `AUTH_USER_MODEL`.

  2. El registro de organización NO devuelve tokens. Devuelve 201 y la
     organización tiene que hacer login después. Esto evita el caso raro en
     que alguien obtiene un token sin haber pasado por `/login/` y sin que
     quede registro de ese acceso. Para el profesional el camino principal es
     distinto: se postula por `POST /api/postulaciones/`, que sí es público.

El envío de correos nunca hace fallar el endpoint: la operación ya está
persistida cuando se manda el correo, así que una falla de SES no puede
convertir un registro exitoso en un error 500.
"""
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from binascii import Error as BinasciiError

from django.utils.encoding import (
    DjangoUnicodeDecodeError,
    force_bytes,
    force_str,
)
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.timezone import now
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import ValidationError as DRFValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.usuarios.permisos import EsAdmin, EsOrganizacion, EsProfesional
from apps.usuarios.serializers import (
    CambiarPasswordSerializer,
    HorarioSerializer,
    LoginSerializer,
    MiPerfilProfesionalSerializer,
    MiPerfilSerializer,
    OrganizacionAdminSerializer,
    OrganizacionSerializer,
    PasswordResetConfirmarSerializer,
    PasswordResetSerializer,
    ProfesionalAdminSerializer,
    ProfesionalSerializer,
    RegistroOrganizacionSerializer,
)

from .correo import (
    enviar_bienvenida_organizacion,
    enviar_password_reset,
)
from .models import Horario, Organizacion, Profesional

logger = logging.getLogger(__name__)
Usuario = get_user_model()


def _tokens_para(usuario):
    refresh = RefreshToken.for_user(usuario)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegistroOrganizacionView(APIView):
    """POST /api/auth/registro-organizacion/ — ticket 1.6.

    Público. No devuelve tokens: la organización hace login después.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegistroOrganizacionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organizacion = serializer.save()

        enviar_bienvenida_organizacion(organizacion)

        return Response(
            OrganizacionSerializer(organizacion).data, status=status.HTTP_201_CREATED
        )


class LoginView(APIView):
    """POST /api/auth/login/ — ticket 1.7.

    Login por email. Si el usuario existe pero es `inactivo`, la respuesta es
    401 con un mensaje distinto al de credenciales inválidas: es una
    diferencia de producto que el usuario necesita ver.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        usuario = authenticate(
            request, username=email, password=password
        )

        if usuario is None:
            # Se busca el usuario solo para poder distinguir "inactivo" de
            # "credenciales incorrectas". No se filtra información sensible:
            # ambos casos son 401.
            candidato = Usuario.objects.filter(email__iexact=email).first()
            if candidato is not None and not candidato.is_active:
                return Response(
                    {
                        "detail": (
                            "Tu cuenta está inactiva. Escríbenos para reactivarla."
                        )
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            return Response(
                {"detail": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        respuesta = _tokens_para(usuario)
        respuesta["usuario"] = MiPerfilSerializer(usuario).data
        return Response(respuesta, status=status.HTTP_200_OK)


class MiPerfilView(APIView):
    """GET /api/auth/me/ — quién soy. Ticket 1.7.

    `SimpleJWT` ya deja `request.user` como `is_authenticated=True` para
    cualquier token válido, así que no hace falta permiso extra.
    """

    def get(self, request):
        return Response(MiPerfilSerializer(request.user).data)

    def patch(self, request):
        serializer = MiPerfilSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CambiarPasswordView(APIView):
    """POST /api/auth/cambiar-password/ — ticket 1.9.

    Exige la contraseña actual. Sin eso, un token robado permitiría dejar la
    cuenta inutilizable.
    """

    def post(self, request):
        serializer = CambiarPasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Contraseña actualizada."})


class PasswordResetView(APIView):
    """POST /api/auth/password-reset/ — ticket 1.10.

    Siempre responde 200, exista o no el correo. Si el endpoint dijera "no
    encontramos ese correo", cualquiera podría usarla para averiguar qué
    correos están registrados en la plataforma.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        usuario = Usuario.objects.filter(email__iexact=email, is_active=True).first()

        if usuario is not None:
            uid = urlsafe_base64_encode(force_bytes(usuario.pk))
            token = default_token_generator.make_token(usuario)

            base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
            enlace = f"{base}/restablecer-password/{uid}/{token}"
            enviar_password_reset(usuario, enlace)

        # Respuesta idéntica en ambos casos (anti-enumeración).
        return Response(
            {
                "detail": (
                    "Si ese correo tiene una cuenta en Skilly, te enviamos un "
                    "enlace para restablecer la contraseña."
                )
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmarView(APIView):
    """POST /api/auth/password-reset/confirmar/ — ticket 1.10.

    El token es el de Django (`PasswordResetTokenGenerator`): tiene fecha de
    expiración y es de un solo uso, porque al cambiar la contraseña cambia
    `last_login`/hash y el token deja de validar.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            uid = force_str(urlsafe_base64_decode(serializer.validated_data["uid"]))
        except (DjangoUnicodeDecodeError, ValueError, TypeError, BinasciiError) as exc:
            raise DRFValidationError(
                {"uid": "El enlace no es válido. Pide uno nuevo."}
            ) from exc

        token = serializer.validated_data["token"]
        nueva = serializer.validated_data["password"]

        usuario = Usuario.objects.filter(pk=uid, is_active=True).first()
        if usuario is None or not default_token_generator.check_token(usuario, token):
            raise DRFValidationError(
                {"detail": "El enlace no es válido o venció. Pide uno nuevo."}
            )

        try:
            validate_password(nueva, user=usuario)
        except DjangoValidationError as exc:
            raise DRFValidationError({"password": list(exc.messages)}) from exc

        usuario.set_password(nueva)
        usuario.save()
        return Response({"detail": "Contraseña restablecida."})


class MiPerfilProfesionalView(APIView):
    """GET/PATCH /api/auth/mi-perfil-profesional/ — ticket 1.9.

    Solo el perfil profesional. La organización usa `/me/`.
    """

    permission_classes = [EsProfesional]

    def get(self, request):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")
        return Response(MiPerfilProfesionalSerializer(profesional).data)

    def patch(self, request):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")
        serializer = MiPerfilProfesionalSerializer(
            profesional, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class HorariosView(APIView):
    """GET/POST /api/auth/mis-horarios/ — ticket 1.9.

    Horarios personalizados: el profesional declara su disponibilidad. Es un
    conjunto, no un recurso singular, así que no hay detail en la colección.
    """

    permission_classes = [EsProfesional]

    def get(self, request):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")
        horarios = Horario.objects.filter(profesional=profesional).order_by(
            "dia_semana", "hora_inicio"
        )
        return Response(HorarioSerializer(horarios, many=True).data)

    def post(self, request):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")

        serializer = HorarioSerializer(
            data=request.data, context={"profesional": profesional}
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                horario = serializer.save(profesional=profesional)
        except IntegrityError:
            raise DRFValidationError(
                {
                    "dia_semana": (
                        "Ya tienes un bloque para ese día. Edítalo o "
                        "desactívalo antes de crear otro."
                    )
                }
            )

        return Response(HorarioSerializer(horario).data, status=status.HTTP_201_CREATED)


class HorarioDetailView(APIView):
    """PATCH/DELETE /api/auth/mis-horarios/{id}/ — ticket 1.9."""

    permission_classes = [EsProfesional]

    def _horario(self, request, pk):
        profesional = getattr(request.user, "profesional", None)
        if profesional is None:
            raise NotFound("Tu cuenta no tiene perfil profesional.")
        horario = Horario.objects.filter(pk=pk, profesional=profesional).first()
        if horario is None:
            # 404 y no 403: el profesional no debe saber si ese bloque existe
            # pero es de otro.
            raise NotFound("Horario no encontrado.")
        return horario

    def patch(self, request, pk):
        horario = self._horario(request, pk)
        serializer = HorarioSerializer(
            horario,
            data=request.data,
            partial=True,
            context={"profesional": profesional},
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise DRFValidationError(
                {"dia_semana": "Ya tienes un bloque para ese día."}
            )
        return Response(serializer.data)

    def delete(self, request, pk):
        horario = self._horario(request, pk)
        horario.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Panel de administración (ticket 1.14)
# ===========================================================================
class AdminListarOrganizacionesView(APIView):
    """GET /api/auth/admin/organizaciones/ — ticket 1.14.

    Soporta `?q=` para buscar por nombre, RUT o correo de contacto, y `?modo=`
    para separar las creadas por una reserva sin cuenta (D7).
    """

    permission_classes = [EsAdmin]

    def get(self, request):
        qs = Organizacion.objects.select_related("usuario").order_by("nombre")

        modo = request.query_params.get("modo")
        if modo:
            qs = qs.filter(modo=modo)

        busqueda = (request.query_params.get("q") or "").strip()
        if busqueda:
            from django.db.models import Q

            rut_busqueda = busqueda.replace(".", "").replace("-", "").replace(" ", "")
            qs = qs.filter(
                Q(nombre__icontains=busqueda)
                | Q(rut__icontains=rut_busqueda)
                | Q(email_contacto__icontains=busqueda)
                | Q(usuario__email__icontains=busqueda)
            )

        return Response(OrganizacionAdminSerializer(qs, many=True).data)


class AdminListarProfesionalesView(APIView):
    """GET /api/auth/admin/profesionales/ — ticket 1.14."""

    permission_classes = [EsAdmin]

    def get(self, request):
        qs = Profesional.objects.select_related("usuario").order_by("nombre_completo")

        estado = request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)

        busqueda = (request.query_params.get("q") or "").strip()
        if busqueda:
            from django.db.models import Q

            rut_busqueda = busqueda.replace(".", "").replace("-", "").replace(" ", "")
            qs = qs.filter(
                Q(nombre_completo__icontains=busqueda)
                | Q(rut__icontains=rut_busqueda)
                | Q(usuario__email__icontains=busqueda)
            )

        return Response(ProfesionalAdminSerializer(qs, many=True).data)