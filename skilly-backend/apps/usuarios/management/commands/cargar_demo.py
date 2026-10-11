"""
Comando cargar_demo. Sprint 3.

Deja el entorno listo para probar el flujo de reservas de punta a punta:
  - un profesional aprobado (juan@test.skilly)
  - una organización registrada (org@test.skilly)
  - el horario semanal del profesional (sin horario no hay slots)
  - algunos servicios aprobados, si el profesional todavía no tiene

Es idempotente: se puede correr las veces que haga falta. Asume que las
categorías ya existen (cargar_seed), pero también las crea si faltan.

Uso:
    python manage.py cargar_demo
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalogo.models import Categoria, Servicio
from apps.usuarios.models import Horario, Organizacion, Profesional

CATEGORIAS = [
    ("Salud y Bienestar", "salud-y-bienestar"),
    ("Desarrollo software", "desarrollo-software"),
    ("Diseño gráfico", "diseno-grafico"),
    ("Marketing", "marketing"),
    ("Finanzas", "finanzas"),
]

EMAIL_PROFESIONAL = "juan@test.skilly"
PASSWORD_PROFESIONAL = "ProfTest123!"
EMAIL_ORGANIZACION = "org@test.skilly"
PASSWORD_ORGANIZACION = "OrgTest123!"

DIAS_HABILES = range(5)  # lunes a viernes

SERVICIOS_EJEMPLO = [
    ("Landing page profesional", "desarrollo-software", 250000, "remoto", "2 semanas"),
    ("Identidad visual básica", "diseno-grafico", 180000, "remoto", "1 semana"),
    ("Campaña de contenidos 30 días", "marketing", 300000, "remoto", "1 mes"),
    ("Asesoría financiera PYME", "finanzas", 150000, "semipresencial", "3 horas"),
    ("Taller de bienestar laboral", "salud-y-bienestar", 200000, "presencial", "1 día"),
]


class Command(BaseCommand):
    help = "Carga datos demo (profesional, organización, horarios, servicios)."

    @transaction.atomic
    def handle(self, *args, **opciones):
        Usuario = get_user_model()

        for nombre, slug in CATEGORIAS:
            Categoria.objects.get_or_create(
                slug=slug, defaults={"nombre": nombre, "aprobada": True}
            )

        # --- Profesional (la contraseña solo se fija al crear la cuenta) ---
        usuario_prof, creado_prof = Usuario.objects.get_or_create(
            email=EMAIL_PROFESIONAL,
            defaults={
                "first_name": "Juan",
                "last_name": "Perez",
                "tipo": Usuario.TIPO_PROFESIONAL,
            },
        )
        if creado_prof:
            usuario_prof.set_password(PASSWORD_PROFESIONAL)
            usuario_prof.save(update_fields=["password"])

        profesional, _ = Profesional.objects.get_or_create(
            usuario=usuario_prof,
            defaults={
                "nombre_completo": "Juan Perez",
                "rut": "23181746-0",
                "telefono": "+56987654321",
                "ciudad": "Santiago",
                "estado": Profesional.ESTADO_APROBADO,
            },
        )
        if profesional.estado != Profesional.ESTADO_APROBADO:
            profesional.estado = Profesional.ESTADO_APROBADO
            profesional.save(update_fields=["estado"])

        # --- Organización ---
        usuario_org, creado_org = Usuario.objects.get_or_create(
            email=EMAIL_ORGANIZACION,
            defaults={
                "first_name": "Marcela",
                "last_name": "Ibanez",
                "tipo": Usuario.TIPO_ORGANIZACION,
            },
        )
        if creado_org:
            usuario_org.set_password(PASSWORD_ORGANIZACION)
            usuario_org.save(update_fields=["password"])

        Organizacion.objects.get_or_create(
            usuario=usuario_org,
            defaults={
                "nombre": "Constructora Alba",
                "giro": "Construcción",
                "nombre_contacto": "Marcela Ibanez",
                "email_contacto": EMAIL_ORGANIZACION,
                "telefono": "+56912345678",
                "rut": "15686734-5",
                "modo": Organizacion.MODO_REGISTRADA,
            },
        )

        # --- Horario del profesional (sin esto no hay slots) ---
        if not Horario.objects.filter(profesional=profesional).exists():
            for dia in DIAS_HABILES:
                Horario.objects.create(
                    profesional=profesional,
                    dia_semana=dia,
                    hora_inicio="09:00",
                    hora_fin="18:00",
                    activo=True,
                )
            self.stdout.write(
                self.style.SUCCESS("Horario semanal creado (L-V 09:00-18:00).")
            )
        else:
            self.stdout.write("El profesional ya tiene horario.")

        # --- Servicios de ejemplo ---
        if not Servicio.objects.filter(profesional=profesional).exists():
            self._crear_servicios(profesional)
        else:
            self.stdout.write("El profesional ya tiene servicios.")

        self.stdout.write(self.style.SUCCESS("Demo lista."))
        self.stdout.write(f"  Profesional: {EMAIL_PROFESIONAL} / {PASSWORD_PROFESIONAL}")
        self.stdout.write(
            f"  Organización: {EMAIL_ORGANIZACION} / {PASSWORD_ORGANIZACION}"
        )

    def _crear_servicios(self, profesional):
        for titulo, slug, precio, formato, duracion in SERVICIOS_EJEMPLO:
            categoria = Categoria.objects.filter(slug=slug).first()
            if categoria is None:
                continue
            Servicio.objects.create(
                profesional=profesional,
                categoria=categoria,
                titulo=titulo,
                descripcion_corta=f"Servicio de {titulo.lower()} a medida.",
                descripcion_larga=f"Detalle del servicio: {titulo}.",
                precio=precio,
                formato=formato,
                duracion_estimada=duracion,
                estado=Servicio.ESTADO_APROBADO,
                fecha_publicacion=timezone.now(),
            )
        self.stdout.write(self.style.SUCCESS("Servicios de ejemplo creados."))
