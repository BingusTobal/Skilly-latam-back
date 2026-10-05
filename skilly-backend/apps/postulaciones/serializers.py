"""
Serializers de postulaciones. Tickets 1.8, 1.11, 1.13.

Puntos delicados:

  - La postulación es UN SOLO PASO (decisión 1 del Sprint 1):
    `POST /api/postulaciones/` es público y crea Usuario + Profesional +
    Postulacion. No hay "registro de profesional" separado. Los documentos se
    suben después, por `POST /api/postulaciones/{id}/certificados/`, porque un
    archivo no cabe en un cuerpo JSON.

  - LinkedIn (decisión 3): lo que se valida automáticamente es el FORMATO de
    la URL, porque LinkedIn no expone API pública para verificar un perfil. El
    certificado queda `verificado_automatico` y NO entra a la cola de
    moderación. Cualquier otro documento entra como `sin_reviewer`.
    Esa distinción se documenta acá y en el help del frontend, para que nadie
    la lea como una verificación real de identidad.

  - Moderación separada (R9): aprobar la postulación no cambia el estado de
    los certificados, ni al revés.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import transaction
from rest_framework import serializers

from apps.usuarios.models import Profesional

from .models import Certificado, Postulacion

Usuario = get_user_model()

URL_VALIDADOR = URLValidator()

PREFIJOS_LINKEDIN = (
    "https://www.linkedin.com/in/",
    "https://linkedin.com/in/",
    "http://www.linkedin.com/in/",
    "http://linkedin.com/in/",
)


def es_url_linkedin(url):
    """True si la URL tiene la forma de un perfil público de LinkedIn."""
    if not url:
        return False
    url = url.strip()
    return url.lower().startswith(PREFIJOS_LINKEDIN)


# ===========================================================================
# Certificados
# ===========================================================================
class CertificadoSerializer(serializers.ModelSerializer):
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    archivo_url = serializers.SerializerMethodField()
    requiere_moderacion = serializers.BooleanField(read_only=True)

    class Meta:
        model = Certificado
        fields = [
            "id",
            "tipo",
            "nombre",
            "archivo",
            "archivo_url",
            "enlace",
            "estado",
            "estado_nombre",
            "requiere_moderacion",
            "comentario_revisor",
            "cargado_en",
            "fecha_revision",
        ]
        read_only_fields = [
            "id",
            "archivo_url",
            "estado",
            "estado_nombre",
            "requiere_moderacion",
            "comentario_revisor",
            "cargado_en",
            "fecha_revision",
        ]

    def get_archivo_url(self, obj):
        if not obj.archivo:
            return None
        try:
            return obj.archivo.url
        except ValueError:
            return None

    def validate(self, attrs):
        tipo = attrs.get("tipo", Certificado.TIPO_OTRO)
        enlace = attrs.get("enlace", "")
        archivo = attrs.get("archivo")

        if tipo == Certificado.TIPO_LINKEDIN:
            if not enlace:
                raise serializers.ValidationError(
                    {"enlace": "Para tipo LinkedIn se requiere la URL del perfil."}
                )
            if not es_url_linkedin(enlace):
                raise serializers.ValidationError(
                    {
                        "enlace": (
                            "La URL debe empezar con https://www.linkedin.com/in/ "
                            "para considerarse un perfil de LinkedIn."
                        )
                    }
                )
        else:
            if not archivo and not self.instance:
                raise serializers.ValidationError(
                    {"archivo": "Un documento requiere un archivo adjunto."}
                )

        if archivo:
            # 5 MB, PDF o imagen. El límite va acá además del upload_to.
            if archivo.size > 5 * 1024 * 1024:
                raise serializers.ValidationError(
                    {"archivo": "El archivo supera el máximo de 5 MB."}
                )
            permitido = {"application/pdf", "image/jpeg", "image/png"}
            if archivo.content_type and archivo.content_type not in permitido:
                raise serializers.ValidationError(
                    {"archivo": "Solo se aceptan PDF, JPG o PNG."}
                )

        return attrs

    def create(self, validated_data):
        postulacion = self.context["postulacion"]
        tipo = validated_data.get("tipo", Certificado.TIPO_OTRO)

        # Decisión 3: LinkedIn con URL válida entra ya verificado y fuera de
        # la cola de moderación. El resto, pendiente.
        if tipo == Certificado.TIPO_LINKEDIN and es_url_linkedin(
            validated_data.get("enlace", "")
        ):
            estado = Certificado.ESTADO_VERIFICADO_AUTOMATICO
        else:
            estado = Certificado.ESTADO_SIN_REVISOR

        certificado = Certificado.objects.create(
            postulacion=postulacion, estado=estado, **validated_data
        )
        return certificado


# ===========================================================================
# Postulaciones
# ===========================================================================
class PostulacionSerializer(serializers.ModelSerializer):
    """Salida de la postulación, usada por el profesional para sí mismo."""

    profesional_nombre = serializers.CharField(
        source="profesional.nombre_completo", read_only=True
    )
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    certificados = CertificadoSerializer(many=True, read_only=True)
    tiene_certificados_sin_revisar = serializers.BooleanField(read_only=True)

    class Meta:
        model = Postulacion
        fields = [
            "id",
            "profesional",
            "profesional_nombre",
            "estado",
            "estado_nombre",
            "comentarios_admin",
            "experiencia",
            "especialidad",
            "tiene_certificados_sin_revisar",
            "certificados",
            "fecha_postulacion",
            "fecha_revision",
        ]
        read_only_fields = fields


class PostulacionAdminSerializer(serializers.ModelSerializer):
    """Vista del admin: incluye el RUT y el correo para poder decidir."""

    profesional_nombre = serializers.CharField(
        source="profesional.nombre_completo", read_only=True
    )
    profesional_rut = serializers.CharField(source="profesional.rut", read_only=True)
    profesional_email = serializers.EmailField(
        source="profesional.usuario.email", read_only=True
    )
    profesional_estado = serializers.CharField(
        source="profesional.estado", read_only=True
    )
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    certificados = CertificadoSerializer(many=True, read_only=True)

    class Meta:
        model = Postulacion
        fields = [
            "id",
            "profesional",
            "profesional_nombre",
            "profesional_rut",
            "profesional_email",
            "profesional_estado",
            "estado",
            "estado_nombre",
            "comentarios_admin",
            "experiencia",
            "especialidad",
            "certificados",
            "fecha_postulacion",
            "fecha_revision",
            "revisada_por",
        ]
        read_only_fields = fields


class CrearPostulacionSerializer(serializers.Serializer):
    """POST /api/postulaciones/ — público, un solo paso (decisión 1).

    Crea Usuario + Profesional + Postulacion de forma atómica. Si algo falla
    a mitad de camino no queda nada: la transacción revierte.
    """

    # Datos de la cuenta
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    # Datos del profesional
    nombre_completo = serializers.CharField(max_length=150)
    rut = serializers.CharField(max_length=12)
    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    ciudad = serializers.CharField(max_length=100, required=False, allow_blank=True)
    linkedin_url = serializers.URLField(max_length=255, required=False, allow_blank=True)
    disponibilidad = serializers.ChoiceField(
        choices=Profesional._meta.get_field("disponibilidad").choices,
        required=False,
        default="inmediata",
    )
    # Contenido de la postulación
    especialidad = serializers.CharField(max_length=150, required=False, allow_blank=True)
    experiencia = serializers.CharField(required=False, allow_blank=True)

    # NOTA: los documentos NO se aceptan acá a propósito. Un archivo no puede
    # viajar dentro de un cuerpo JSON, así que un campo `certificados` anidado
    # acá solo parecería funcionar: el upload real va por
    # POST /api/postulaciones/{id}/certificados/ (multipart), que además es la
    # ruta que usa el perfil una vez que la cuenta existe. La postulación
    # pública queda en un solo paso JSON; los documentos, en un paso aparte.

    def validate_email(self, value):
        if Usuario.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Ya existe una cuenta con ese correo.")
        return value.lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_rut(self, value):
        # Se llama al validador del campo directamente: `full_clean()` sobre un
        # Profesional a medio construir exigiría también nombre y usuario, que
        # todavía no están.
        validador = Profesional._meta.get_field("rut").validators[0]
        try:
            validador(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_linkedin_url(self, value):
        if value and not es_url_linkedin(value):
            raise serializers.ValidationError(
                "La URL de LinkedIn debe empezar con https://www.linkedin.com/in/"
            )
        return value

    def validate(self, attrs):
        # El RUT debe ser único entre profesionales y entre organizaciones, pero
        # no entre las dos tablas: son bases separadas a propósito (una persona
        # puede tener los dos roles).
        if Profesional.objects.filter(rut=attrs["rut"]).exists():
            raise serializers.ValidationError(
                {"rut": "Ese RUT ya está asociado a otro profesional."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        email = validated_data.pop("email")
        password = validated_data.pop("password")

        # Si no hay certificado LinkedIn pero sí URL en el perfil, se crea uno
        # automáticamente: el perfil de LinkedIn es el certificado "virtual".
        linkedin_url = validated_data.pop("linkedin_url", "")
        nombre_completo = validated_data["nombre_completo"]

        usuario = Usuario.objects.create_user(
            email=email,
            password=password,
            first_name=nombre_completo.split(" ")[0][:150],
            tipo=Usuario.TIPO_PROFESIONAL,
            is_active=True,
        )

        profesional = Profesional.objects.create(
            usuario=usuario,
            nombre_completo=nombre_completo,
            rut=validated_data["rut"],
            telefono=validated_data.get("telefono", ""),
            ciudad=validated_data.get("ciudad", ""),
            linkedin_url=linkedin_url,
            disponibilidad=validated_data.get("disponibilidad", "inmediata"),
            estado=Profesional.ESTADO_POSTULANDO,
        )

        postulacion = Postulacion.objects.create(
            profesional=profesional,
            estado=Postulacion.ESTADO_PENDIENTE,
            especialidad=validated_data.get("especialidad", ""),
            experiencia=validated_data.get("experiencia", ""),
        )

        # Certificado LinkedIn derivado de la URL del perfil (decisión 3).
        for _ in range(1 if linkedin_url else 0):
            Certificado.objects.create(
                postulacion=postulacion,
                tipo=Certificado.TIPO_LINKEDIN,
                nombre=f"Perfil de LinkedIn — {nombre_completo}"[:150],
                enlace=linkedin_url,
                estado=Certificado.ESTADO_VERIFICADO_AUTOMATICO,
            )

        return {
            "usuario": usuario,
            "profesional": profesional,
            "postulacion": postulacion,
        }

    def to_representation(self, instance):
        postulacion = instance["postulacion"]
        return {
            "postulacion": PostulacionSerializer(
                postulacion, context=self.context
            ).data,
            "mensaje": (
                "Recibimos tu postulación. Te avisamos por correo cuando la "
                "revisemos."
            ),
        }


class ModerarPostulacionSerializer(serializers.Serializer):
    """Body de aprobar / rechazar / devolver."""

    comentarios_admin = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )

    def validate(self, attrs):
        if self.context.get("accion") in ("rechazar", "devolver"):
            if not attrs.get("comentarios_admin", "").strip():
                raise serializers.ValidationError(
                    {
                        "comentarios_admin": (
                            "Es obligatorio escribir comentarios al devolver o "
                            "rechazar: el profesional los necesita para saber "
                            "qué corregir."
                        )
                    }
                )
        return attrs


class ModerarCertificadoSerializer(serializers.Serializer):
    """Body de aprobar / rechazar un certificado (moderación separada)."""

    comentario_revisor = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )