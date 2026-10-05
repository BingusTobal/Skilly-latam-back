"""
Serializers de usuarios y horarios. Tickets 1.6 a 1.9.

`MiPerfilSerializer` es el que devuelve el login y `/me/`, así que es el que
define qué ve un usuario de sí mismo. `MiPerfilProfesionalSerializer` expone
el perfil público del profesional: nunca el `estado` como campo editable.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import Horario, Organizacion, Profesional

Usuario = get_user_model()


def _validar_password(value, usuario=None):
    try:
        validate_password(value, user=usuario)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc
    return value


class MiPerfilSerializer(serializers.ModelSerializer):
    """Lo que el usuario ve de sí mismo."""

    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    def get_organizacion_id(self, obj):
        organizacion = getattr(obj, "organizacion", None)
        return organizacion.pk if organizacion else None

    def get_profesional_id(self, obj):
        profesional = getattr(obj, "profesional", None)
        return profesional.pk if profesional else None
    # `source` va al objeto de la relacion inversa, no a su `_id`: una
    # OneToOneField inversa no expone `<nombre>_id` en el lado del usuario, así
    # que `IntegerField(source="organizacion_id")` daba None aunque la
    # organizacion existiera.
    organizacion_id = serializers.SerializerMethodField()
    profesional_id = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "tipo",
            "tipo_nombre",
            "is_admin",
            "organizacion_id",
            "profesional_id",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "tipo", "is_admin", "date_joined"]


class RegistroOrganizacionSerializer(serializers.ModelSerializer):
    """POST /api/auth/registro-organizacion/. Ticket 1.6.

    `password_confirmacion` se compara en `validate`, no en el modelo, porque
    es una comprobación de formulario y no una regla de negocio del
    Organizacion.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirmacion = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    class Meta:
        model = Organizacion
        fields = [
            "id",
            "nombre",
            "giro",
            "nombre_contacto",
            "email_contacto",
            "telefono",
            "rut",
            "password",
            "password_confirmacion",
        ]

    def validate_email_contacto(self, value):
        # El correo de contacto puede repetirse entre organizaciones: son
        # contactos, no cuentas. Solo se normaliza.
        return value.lower()

    def validate_password(self, value):
        return _validar_password(value)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirmacion"]:
            raise serializers.ValidationError(
                {"password_confirmacion": "Las contraseñas no coinciden."}
            )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.pop("password_confirmacion", None)

        email = validated_data["email_contacto"]

        try:
            with transaction.atomic():
                usuario = Usuario.objects.create_user(
                    email=email,
                    password=password,
                    first_name=validated_data["nombre_contacto"].split(" ")[0][:150],
                    tipo=Usuario.TIPO_ORGANIZACION,
                    is_active=True,
                )
                organizacion = Organizacion.objects.create(
                    usuario=usuario,
                    nombre_contacto=validated_data["nombre_contacto"],
                    email_contacto=email,
                    modo=Organizacion.MODO_REGISTRADA,
                    **{
                        k: v
                        for k, v in validated_data.items()
                        if k not in ("nombre_contacto", "email_contacto")
                    },
                )
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"email_contacto": "Ya existe una cuenta con ese correo."}
            ) from exc

        return organizacion


class OrganizacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organizacion
        fields = [
            "id",
            "nombre",
            "giro",
            "nombre_contacto",
            "email_contacto",
            "telefono",
            "rut",
            "modo",
            "activa",
            "creada_en",
        ]
        read_only_fields = fields


class OrganizacionAdminSerializer(OrganizacionSerializer):
    """Vista admin: incluye si tiene usuario o se creó por reserva (D7)."""

    usuario_email = serializers.EmailField(source="usuario.email", read_only=True, allow_null=True)
    tiene_usuario = serializers.SerializerMethodField()
    modo_nombre = serializers.CharField(source="get_modo_display", read_only=True)

    class Meta(OrganizacionSerializer.Meta):
        fields = OrganizacionSerializer.Meta.fields + [
            "usuario_email",
            "tiene_usuario",
            "modo_nombre",
        ]
        read_only_fields = fields

    def get_tiene_usuario(self, obj):
        return obj.usuario_id is not None


class LoginSerializer(serializers.Serializer):
    """POST /api/auth/login/. Ticket 1.7."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_email(self, value):
        return value.lower()


class CambiarPasswordSerializer(serializers.Serializer):
    """POST /api/auth/cambiar-password/. Ticket 1.9."""

    password_actual = serializers.CharField(write_only=True)
    password_nueva = serializers.CharField(write_only=True)
    password_confirmacion = serializers.CharField(write_only=True)

    def validate_password_actual(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("La contraseña actual no es correcta.")
        return value

    def validate(self, attrs):
        if attrs["password_nueva"] != attrs["password_confirmacion"]:
            raise serializers.ValidationError(
                {"password_confirmacion": "Las contraseñas no coinciden."}
            )
        _validar_password(attrs["password_nueva"], self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        usuario = self.context["request"].user
        usuario.set_password(self.validated_data["password_nueva"])
        usuario.save()
        return usuario


class PasswordResetSerializer(serializers.Serializer):
    """POST /api/auth/password-reset/. Ticket 1.10."""

    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class PasswordResetConfirmarSerializer(serializers.Serializer):
    """POST /api/auth/password-reset/confirmar/. Ticket 1.10.

    `uid` y `token` vienen de la URL que se envió por correo, no del cuerpo
    libre: así el cliente no puede inventarse un uid.
    """

    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)
    password_confirmacion = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirmacion"]:
            raise serializers.ValidationError(
                {"password_confirmacion": "Las contraseñas no coinciden."}
            )
        _validar_password(attrs["password"])
        return attrs


class MiPerfilProfesionalSerializer(serializers.ModelSerializer):
    """Perfil profesional visible por su dueño. Ticket 1.9."""

    email = serializers.EmailField(source="usuario.email", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    postulacion_estado = serializers.SerializerMethodField()
    postulacion_id = serializers.SerializerMethodField()

    class Meta:
        model = Profesional
        fields = [
            "id",
            "nombre_completo",
            "rut",
            "email",
            "telefono",
            "ciudad",
            "linkedin_url",
            "disponibilidad",
            "bio",
            "estado",
            "estado_nombre",
            "postulacion_id",
            "postulacion_estado",
            "creado_en",
            "fecha_estado",
        ]
        read_only_fields = ["rut", "estado", "estado_nombre", "creado_en", "fecha_estado"]

    def get_postulacion_id(self, obj):
        postulacion = obj.postulaciones.order_by("-fecha_postulacion").first()
        return postulacion.pk if postulacion else None

    def get_postulacion_estado(self, obj):
        postulacion = obj.postulaciones.order_by("-fecha_postulacion").first()
        return postulacion.get_estado_display() if postulacion else None


class ProfesionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profesional
        fields = [
            "id",
            "nombre_completo",
            "ciudad",
            "disponibilidad",
            "bio",
            "estado",
        ]
        read_only_fields = fields


class ProfesionalAdminSerializer(ProfesionalSerializer):
    """Vista admin: agrega correo y estado de la postulación."""

    usuario_email = serializers.EmailField(source="usuario.email", read_only=True, allow_null=True)
    postulaciones_pendientes = serializers.SerializerMethodField()

    class Meta(ProfesionalSerializer.Meta):
        fields = ProfesionalSerializer.Meta.fields + [
            "usuario_email",
            "postulaciones_pendientes",
        ]
        read_only_fields = fields

    def get_postulaciones_pendientes(self, obj):
        return obj.postulaciones.filter(estado="pendiente").count()


class HorarioSerializer(serializers.ModelSerializer):
    """Horario personalizado del profesional. Ticket 1.9."""

    profesional_nombre = serializers.CharField(
        source="profesional.nombre_completo", read_only=True
    )
    resumen = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = Horario
        fields = [
            "id",
            "profesional",
            "profesional_nombre",
            "dia_semana",
            "hora_inicio",
            "hora_fin",
            "activo",
            "hora_inicio",
            "hora_fin",
            "resumen",
        ]
        read_only_fields = ["id", "profesional", "profesional_nombre"]

    def validate(self, attrs):
        inicio = attrs.get("hora_inicio", getattr(self.instance, "hora_inicio", None))
        fin = attrs.get("hora_fin", getattr(self.instance, "hora_fin", None))
        if inicio is None or fin is None:
            # Faltan horas: que lo diga el campo, no la validación cruzada.
            return attrs

        if inicio and fin and fin <= inicio:
            raise serializers.ValidationError(
                {"hora_fin": "La hora de término debe ser posterior a la de inicio."}
            )

        # El solapamiento con otros bloques del mismo día vive en
        # `Horario.clean()`, y DRF NO llama a `clean()`: solo valida los campos
        # declarados. Sin esto, la API aceptaría bloques que pisan entre sí y
        # la regla solo se cumpliría en el admin.
        # En un POST el profesional todavía no está en `attrs` (lo inyecta la
        # vista al guardar), así que llega por el contexto.
        propietario = attrs.get(
            "profesional", getattr(self.instance, "profesional", None)
        ) or self.context.get("profesional")

        candidato = Horario(
            profesional=propietario,
            dia_semana=attrs.get(
                "dia_semana", getattr(self.instance, "dia_semana", None)
            ),
            hora_inicio=inicio,
            hora_fin=fin,
            activo=attrs.get("activo", getattr(self.instance, "activo", True)),
        )
        if self.instance is not None:
            candidato.pk = self.instance.pk

        try:
            candidato.full_clean(exclude=["profesional"])
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict) from exc
            raise serializers.ValidationError(list(exc.messages)) from exc

        return attrs