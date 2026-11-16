"""Serializers de reservas (ticket 3.3).

Regla de negocio: el profesional ve SOLO el monto neto (`monto_neto`), nunca el
desglose bruto + comisión. Por eso su serializer no expone `precio_acordado`.
La organización ve el precio que paga (`precio_acordado`).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalogo.models import Servicio
from apps.usuarios.models import validar_rut

from .models import Disputa, EvidenciaDisputa, Reserva

TIPOS_EVIDENCIA = {"application/pdf", "image/jpeg", "image/png"}
MAX_EVIDENCIA_BYTES = 5 * 1024 * 1024


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

    def validate_rut(self, valor):
        if not valor:
            return valor
        try:
            validar_rut(valor)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return valor


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
    disputa = serializers.SerializerMethodField()

    def get_disputa(self, obj):
        return _disputa_resumen(obj)

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
            "disputa",
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
    disputa = serializers.SerializerMethodField()

    def get_disputa(self, obj):
        return _disputa_resumen(obj)

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
            "disputa",
            "creada_en",
            "expira_en",
        )
        read_only_fields = fields


class AccionReservaSerializer(serializers.Serializer):
    """Cuerpo genérico para acciones con texto libre."""

    motivo = serializers.CharField(max_length=200, required=False, allow_blank=True)
    descripcion = serializers.CharField(max_length=2000, required=False, allow_blank=True)


def _disputa_resumen(reserva):
    """Disputa asociada a la reserva, si existe (se serializa al vuelo)."""
    disputa = getattr(reserva, "disputa", None)
    if disputa is None:
        return None
    return DisputaSerializer(disputa).data


def validar_evidencia(archivo):
    """Valida tipo y tamaño de un archivo de evidencia (ticket 5.2)."""
    if archivo.size > MAX_EVIDENCIA_BYTES:
        raise serializers.ValidationError("El archivo supera el máximo de 5 MB.")
    if archivo.content_type and archivo.content_type not in TIPOS_EVIDENCIA:
        raise serializers.ValidationError("Solo se aceptan PDF, JPG o PNG.")
    return archivo


class EvidenciaDisputaSerializer(serializers.ModelSerializer):
    archivo = serializers.SerializerMethodField()
    subida_por = serializers.SerializerMethodField()

    class Meta:
        model = EvidenciaDisputa
        fields = ("id", "nombre", "archivo", "subida_por", "creada_en")

    def get_archivo(self, obj):
        try:
            return obj.archivo.url
        except ValueError:
            return None

    def get_subida_por(self, obj):
        if obj.subida_por is None:
            return None
        return obj.subida_por.get_full_name() or obj.subida_por.email


class DisputaSerializer(serializers.ModelSerializer):
    """Disputa vista por las partes de la reserva."""

    reserva = serializers.IntegerField(source="reserva_id", read_only=True)
    servicio = serializers.CharField(source="reserva.servicio.titulo", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    resultado_nombre = serializers.CharField(
        source="get_resultado_display", read_only=True
    )
    abierta_por = serializers.SerializerMethodField()
    monto = serializers.DecimalField(
        source="reserva.precio_acordado",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    monto_reembolso = serializers.SerializerMethodField()
    evidencias = EvidenciaDisputaSerializer(many=True, read_only=True)

    class Meta:
        model = Disputa
        fields = (
            "id",
            "reserva",
            "servicio",
            "motivo",
            "descripcion",
            "estado",
            "estado_nombre",
            "abierta_por",
            "monto",
            "resultado",
            "resultado_nombre",
            "porcentaje_reembolso",
            "monto_reembolso",
            "resolucion",
            "evidencias",
            "creada_en",
            "actualizada_en",
            "resuelta_en",
        )
        read_only_fields = fields

    def get_abierta_por(self, obj):
        if obj.abierta_por is None:
            return None
        return obj.abierta_por.get_full_name() or obj.abierta_por.email

    def get_monto_reembolso(self, obj):
        if obj.resultado != Disputa.RESULTADO_DIVISION or not obj.porcentaje_reembolso:
            return None
        total = obj.reserva.precio_acordado
        return (total * obj.porcentaje_reembolso / 100).quantize(Decimal("0.01"))


class CrearDisputaSerializer(serializers.Serializer):
    """Cuerpo de POST /api/disputas/ (organización o profesional)."""

    reserva = serializers.PrimaryKeyRelatedField(queryset=Reserva.objects.all())
    motivo = serializers.CharField(max_length=200)
    descripcion = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    evidencia = serializers.FileField(required=False, write_only=True)

    def validate_evidencia(self, archivo):
        return validar_evidencia(archivo)


class EvidenciaDisputaUploadSerializer(serializers.Serializer):
    archivo = serializers.FileField()
    nombre = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_archivo(self, archivo):
        return validar_evidencia(archivo)


class ResolverDisputaSerializer(serializers.Serializer):
    resultado = serializers.ChoiceField(choices=Disputa.RESULTADO_CHOICES)
    resolucion = serializers.CharField(max_length=2000)
    porcentaje_reembolso = serializers.IntegerField(
        min_value=1, max_value=99, required=False
    )

    def validate(self, attrs):
        if attrs["resultado"] == Disputa.RESULTADO_DIVISION:
            if not attrs.get("porcentaje_reembolso"):
                raise serializers.ValidationError(
                    {"porcentaje_reembolso": "Indica el porcentaje de la división."}
                )
        else:
            attrs.pop("porcentaje_reembolso", None)
        return attrs


class DisputaAdminSerializer(DisputaSerializer):
    """Cola de disputas del panel admin (tickets 1.14 y 5.3).

    El admin necesita ver el caso completo (partes, pago y evidencia) para
    poder resolverlo.
    """

    organizacion = serializers.CharField(
        source="reserva.organizacion.nombre", read_only=True
    )
    profesional = serializers.CharField(
        source="reserva.profesional.nombre_completo", read_only=True
    )
    pago_estado = serializers.SerializerMethodField()
    monto_retenido = serializers.SerializerMethodField()

    class Meta(DisputaSerializer.Meta):
        fields = DisputaSerializer.Meta.fields + (
            "organizacion",
            "profesional",
            "pago_estado",
            "monto_retenido",
        )
        read_only_fields = fields

    def _pago(self, obj):
        return obj.reserva.pagos.order_by("-creado_en").first()

    def get_pago_estado(self, obj):
        pago = self._pago(obj)
        return pago.estado if pago else None

    def get_monto_retenido(self, obj):
        pago = self._pago(obj)
        if pago is None:
            return None
        return pago.monto_total - pago.monto_reembolsado
