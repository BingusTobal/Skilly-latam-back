"""Serializers de reservas (ticket 3.3).

Regla de negocio: el profesional ve SOLO el monto neto (`monto_neto`), nunca el
desglose bruto + comisión. Por eso su serializer no expone `precio_acordado`.
La organización ve el precio que paga (`precio_acordado`).
"""
from rest_framework import serializers

from apps.catalogo.models import Servicio

from .models import Reserva


class CrearReservaSerializer(serializers.Serializer):
    """Cuerpo de POST /api/reservas/ (reserva con o sin cuenta)."""

    servicio = serializers.PrimaryKeyRelatedField(
        queryset=Servicio.objects.filter(estado=Servicio.ESTADO_APROBADO, activo=True)
    )
    fecha = serializers.DateField()
    hora_inicio = serializers.TimeField()
    nombre = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    empresa = serializers.CharField(max_length=200, required=False, allow_blank=True)
    rut = serializers.CharField(max_length=12, required=False, allow_blank=True)
    mensaje = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class ReservaResumenServicioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicio
        fields = ("id", "titulo", "slug")


class ReservaOrganizacionSerializer(serializers.ModelSerializer):
    servicio = ReservaResumenServicioSerializer(read_only=True)
    profesional_nombre = serializers.CharField(
        source="profesional.nombre_completo", read_only=True
    )
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    # Regla de negocio: la organización coordina directamente con el profesional
    # una vez aceptada la reserva; antes de eso no se revela el contacto.
    profesional_email = serializers.SerializerMethodField()
    profesional_telefono = serializers.SerializerMethodField()

    ESTADOS_CON_CONTACTO = {
        "en_curso",
        "entregado_por_confirmar",
        "finalizada",
        "con_disputa",
    }

    def _con_contacto(self, obj):
        return obj.estado in self.ESTADOS_CON_CONTACTO and obj.profesional_id

    def get_profesional_email(self, obj):
        if self._con_contacto(obj):
            return obj.profesional.usuario.email
        return None

    def get_profesional_telefono(self, obj):
        if self._con_contacto(obj):
            return obj.profesional.telefono
        return None

    class Meta:
        model = Reserva
        fields = (
            "id",
            "servicio",
            "profesional_nombre",
            "profesional_email",
            "profesional_telefono",
            "fecha",
            "hora_inicio",
            "hora_fin",
            "estado",
            "estado_display",
            "precio_acordado",
            "formato",
            "ubicacion",
            "contacto_nombre",
            "contacto_email",
            "contacto_telefono",
            "mensaje",
            "motivo_rechazo",
            "motivo_cancelacion",
            "creada_en",
            "expira_en",
        )
        read_only_fields = fields


class ReservaProfesionalSerializer(serializers.ModelSerializer):
    """Vista del profesional: contacto de la organización y monto NETO."""

    servicio = ReservaResumenServicioSerializer(read_only=True)
    organizacion_nombre = serializers.CharField(source="organizacion.nombre", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    monto_neto = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Reserva
        fields = (
            "id",
            "servicio",
            "organizacion_nombre",
            "contacto_nombre",
            "contacto_email",
            "contacto_telefono",
            "mensaje",
            "fecha",
            "hora_inicio",
            "hora_fin",
            "estado",
            "estado_display",
            "monto_neto",
            "formato",
            "ubicacion",
            "motivo_rechazo",
            "creada_en",
            "expira_en",
        )
        read_only_fields = fields


class AccionReservaSerializer(serializers.Serializer):
    """Cuerpo genérico para acciones con texto libre."""

    motivo = serializers.CharField(max_length=200, required=False, allow_blank=True)
    descripcion = serializers.CharField(max_length=2000, required=False, allow_blank=True)
