"""Serializers de configuración de comisión (ticket 5.4 / RF-30)."""
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import TasaComision


class TasaComisionSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(
        source="categoria.nombre", read_only=True, default=None
    )
    creada_por_email = serializers.CharField(
        source="creada_por.email", read_only=True, default=None
    )
    porcentaje = serializers.FloatField(read_only=True)

    class Meta:
        model = TasaComision
        fields = [
            "id",
            "categoria",
            "categoria_nombre",
            "tasa",
            "porcentaje",
            "vigente_desde",
            "activa",
            "creada_por",
            "creada_por_email",
            "creada_en",
        ]
        read_only_fields = [
            "id",
            "categoria_nombre",
            "porcentaje",
            "creada_por",
            "creada_por_email",
            "creada_en",
        ]

    def validate_tasa(self, valor):
        if valor is None:
            return valor
        if valor < 0 or valor >= 1:
            raise serializers.ValidationError(
                "La tasa debe ser mayor o igual a 0 y menor que 1 (ej: 0.10 = 10 %)."
            )
        return valor

    def validate(self, attrs):
        # Versionado: una tasa existente solo puede activarse o desactivarse.
        # Para cambiar el porcentaje o la fecha se crea otra fila.
        if self.instance is not None:
            campos_inmutables = {"tasa", "categoria", "vigente_desde"} & set(attrs)
            if campos_inmutables:
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "Las tasas no se editan: crea una nueva versión con su "
                            "propia fecha de vigencia."
                        )
                    }
                )
            return attrs

        categoria = attrs.get("categoria")
        vigente_desde = attrs.get("vigente_desde") or timezone.localdate()
        existentes = TasaComision.objects.filter(vigente_desde=vigente_desde)
        if categoria is None:
            existentes = existentes.filter(categoria__isnull=True)
        else:
            existentes = existentes.filter(categoria=categoria)

        if existentes.exists():
            raise serializers.ValidationError(
                {
                    "vigente_desde": (
                        "Ya existe una tasa para ese alcance y fecha. Elige otra "
                        "fecha de vigencia."
                    )
                }
            )

        return attrs


class TasaVigenteSerializer(serializers.Serializer):
    """Salida de la tasa aplicable a una reserva nueva."""

    tasa = serializers.DecimalField(max_digits=5, decimal_places=4)
    porcentaje = serializers.SerializerMethodField()
    origen = serializers.CharField()
    vigente_desde = serializers.DateField(allow_null=True)
    categoria = serializers.IntegerField(allow_null=True)

    def get_porcentaje(self, obj):
        return float(Decimal(obj["tasa"])) * 100
