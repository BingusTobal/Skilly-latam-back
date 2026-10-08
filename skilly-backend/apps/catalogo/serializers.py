# Serializers para catálogo: Servicio, Entregable, Categoría

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.usuarios.models import Profesional
from .models import Categoria, Entregable, Servicio


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ("id", "nombre", "slug", "aprobada", "activa")
        read_only_fields = fields


class EntregableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entregable
        fields = ("id", "nombre", "descripcion", "orden")
        extra_kwargs = {"id": {"read_only": True}}


class EntregableNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entregable
        fields = ("id", "nombre", "descripcion", "orden")
        extra_kwargs = {"id": {"read_only": True, "required": False}}


class ServicioPublicoSerializer(serializers.ModelSerializer):
    categoria = CategoriaSerializer(read_only=True)
    profesional_nombre = serializers.CharField(source="profesional.nombre_completo", read_only=True)
    profesional_ciudad = serializers.CharField(source="profesional.ciudad", read_only=True)
    entregables = EntregableSerializer(many=True, read_only=True)
    precio_display = serializers.DecimalField(source="precio", max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Servicio
        fields = (
            "id",
            "titulo",
            "slug",
            "descripcion_corta",
            "descripcion_larga",
            "precio",
            "precio_display",
            "formato",
            "ubicacion",
            "duracion_estimada",
            "palabras_clave",
            "categoria",
            "profesional",
            "profesional_nombre",
            "profesional_ciudad",
            "entregables",
            "fecha_creacion",
            "fecha_publicacion",
        )
        read_only_fields = fields


class ServicioDetallePublicoSerializer(ServicioPublicoSerializer):
    sugerencias = serializers.SerializerMethodField()

    class Meta(ServicioPublicoSerializer.Meta):
        fields = ServicioPublicoSerializer.Meta.fields + ("sugerencias",)

    def get_sugerencias(self, obj):
        qs = (
            Servicio.objects.filter(
                estado=Servicio.ESTADO_APROBADO,
                activo=True,
                categoria=obj.categoria,
            )
            .exclude(pk=obj.pk)
            .select_related("profesional", "categoria")
            .prefetch_related("entregables")
            .order_by("-fecha_publicacion", "-fecha_creacion")[:6]
        )
        return ServicioPublicoSerializer(qs, many=True, context=self.context).data


class ServicioProfesionalSerializer(serializers.ModelSerializer):
    categoria = serializers.PrimaryKeyRelatedField(queryset=Categoria.objects.all())
    entregables = EntregableNestedSerializer(many=True, required=False)
    comentarios_admin = serializers.CharField(read_only=True)

    class Meta:
        model = Servicio
        fields = (
            "id",
            "titulo",
            "slug",
            "descripcion_corta",
            "descripcion_larga",
            "precio",
            "formato",
            "ubicacion",
            "duracion_estimada",
            "palabras_clave",
            "categoria",
            "estado",
            "comentarios_admin",
            "activo",
            "entregables",
            "fecha_creacion",
            "fecha_ultima_actualizacion",
            "fecha_publicacion",
            "fecha_revision",
        )
        read_only_fields = (
            "id",
            "slug",
            "estado",
            "comentarios_admin",
            "fecha_creacion",
            "fecha_ultima_actualizacion",
            "fecha_publicacion",
            "fecha_revision",
        )

    def _get_profesional(self):
        request = self.context.get("request")
        if request and hasattr(request.user, "profesional"):
            return request.user.profesional
        return None

    def validate_categoria(self, categoria):
        if not categoria.aprobada or not categoria.activa:
            raise serializers.ValidationError("La categoría debe estar aprobada y activa.")
        return categoria

    def validate(self, attrs):
        profesional = self._get_profesional()
        if self.instance is None and profesional and profesional.estado != Profesional.ESTADO_APROBADO:
            raise serializers.ValidationError(
                "Solo profesionales aprobados pueden crear y publicar servicios."
            )
        return attrs

    def create(self, validated_data):
        entregables_data = validated_data.pop("entregables", [])
        profesional = self._get_profesional()
        servicio = Servicio.objects.create(
            profesional=profesional,
            **validated_data,
        )
        for idx, ed in enumerate(entregables_data):
            ed = dict(ed)
            ed.setdefault("orden", idx)
            Entregable.objects.create(servicio=servicio, **ed)
        return servicio

    def update(self, instance, validated_data):
        entregables_data = validated_data.pop("entregables", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if entregables_data is not None:
            instance.entregables.all().delete()
            for idx, ed in enumerate(entregables_data):
                ed = dict(ed)
                ed.setdefault("orden", idx)
                Entregable.objects.create(servicio=instance, **ed)
        return instance


class ServicioProfesionalDetalleSerializer(ServicioProfesionalSerializer):
    categoria = CategoriaSerializer(read_only=True)
    entregables = EntregableSerializer(many=True, read_only=True)


class ServicioAdminSerializer(serializers.ModelSerializer):
    categoria = CategoriaSerializer(read_only=True)
    profesional = serializers.PrimaryKeyRelatedField(read_only=True)
    profesional_nombre = serializers.CharField(source="profesional.nombre_completo", read_only=True)
    profesional_rut = serializers.CharField(source="profesional.rut", read_only=True)
    profesional_email = serializers.EmailField(source="profesional.usuario.email", read_only=True)
    entregables = EntregableSerializer(many=True, read_only=True)
    revisado_por_email = serializers.EmailField(source="revisado_por.email", read_only=True, allow_null=True)

    class Meta:
        model = Servicio
        fields = (
            "id",
            "titulo",
            "slug",
            "descripcion_corta",
            "descripcion_larga",
            "precio",
            "formato",
            "ubicacion",
            "duracion_estimada",
            "palabras_clave",
            "categoria",
            "profesional",
            "profesional_nombre",
            "profesional_rut",
            "profesional_email",
            "estado",
            "comentarios_admin",
            "activo",
            "entregables",
            "fecha_creacion",
            "fecha_ultima_actualizacion",
            "fecha_publicacion",
            "fecha_revision",
            "revisado_por",
            "revisado_por_email",
        )
        read_only_fields = fields


class ServicioAdminUpdateSerializer(serializers.ModelSerializer):
    comentarios_admin = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Servicio
        fields = ("comentarios_admin",)


class ModerarServicioSerializer(serializers.Serializer):
    comentarios_admin = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        accion = self.context.get("accion")
        if accion in ("devolver", "rechazar"):
            if not (attrs.get("comentarios_admin") or "").strip():
                raise serializers.ValidationError(
                    {"comentarios_admin": "Es obligatorio escribir comentarios al devolver o rechazar."}
                )
        return attrs
