"""
Tests de la lógica de reservas: cálculo de slots, colchón de bloqueo y máquina
de estados (tickets 3.1, 3.2, 3.5, 3.13).
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.reservas import services
from apps.reservas.models import EventoReserva, Reserva


def _datos(email="invitado@test.skilly", **extra):
    base = {"nombre": "Contacto Invitado", "email": email}
    base.update(extra)
    return base


@pytest.mark.django_db
class TestSlots:
    def test_grilla_de_30_minutos(self, servicio_aprobado, horario_semanal, fecha_futura):
        slots = services.calcular_slots(servicio_aprobado, fecha_futura)
        # 09:00 a 18:00 en pasos de 30 min => 18 slots.
        assert len(slots) == 18
        assert slots[0]["hora_inicio"].strftime("%H:%M") == "09:00"
        assert all(s["disponible"] for s in slots)

    def test_colchon_bloquea_3_horas(self, servicio_aprobado, horario_semanal, fecha_futura):
        services.crear_reserva(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora_inicio="10:00",
            datos=_datos(),
        )
        slots = services.calcular_slots(servicio_aprobado, fecha_futura)
        libres = {s["hora_inicio"].strftime("%H:%M") for s in slots if s["disponible"]}
        # 10:00 + 3 h => bloqueados 10:00..12:30; vuelve a estar libre a las 13:00.
        assert "10:00" not in libres
        assert "11:00" not in libres
        assert "12:30" not in libres
        assert "13:00" in libres

    def test_sin_horario_no_hay_slots(self, servicio_aprobado, fecha_futura):
        assert services.calcular_slots(servicio_aprobado, fecha_futura) == []


@pytest.mark.django_db
class TestCrearReserva:
    def test_invitado_crea_cuenta_organizacion_y_token(
        self, servicio_aprobado, horario_semanal, fecha_futura
    ):
        reserva, token = services.crear_reserva(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora_inicio="10:00",
            datos=_datos(rut="15686734-5"),
        )
        assert token
        assert reserva.organizacion.modo == "invitada"
        usuario = reserva.organizacion.usuario
        assert usuario is not None
        assert usuario.tipo == "organizacion"
        assert not usuario.has_usable_password()
        assert usuario.email == "invitado@test.skilly"
        assert reserva.estado == Reserva.ESTADO_PENDIENTE_ACEPTACION
        assert services.buscar_por_token(token) == reserva

    def test_rechaza_slot_no_disponible(self, servicio_aprobado, horario_semanal, fecha_futura):
        services.crear_reserva(
            servicio=servicio_aprobado, fecha=fecha_futura, hora_inicio="10:00", datos=_datos()
        )
        with pytest.raises(ValidationError):
            services.crear_reserva(
                servicio=servicio_aprobado,
                fecha=fecha_futura,
                hora_inicio="11:00",
                datos=_datos(email="otro@test.skilly"),
            )

    def test_rechaza_fecha_pasada(self, servicio_aprobado, horario_semanal):
        ayer = timezone.localdate() - timedelta(days=1)
        with pytest.raises(ValidationError):
            services.crear_reserva(
                servicio=servicio_aprobado, fecha=ayer, hora_inicio="10:00", datos=_datos()
            )


@pytest.mark.django_db
class TestCuentaInvitada:
    """Reserva sin registro crea/enlaza una cuenta automática (Sprint 3)."""

    def _reservar(self, **kwargs):
        return services.crear_reserva(
            servicio=kwargs["servicio"],
            fecha=kwargs["fecha"],
            hora_inicio=kwargs["hora"],
            datos=kwargs["datos"],
        )

    def test_segunda_reserva_reutiliza_la_cuenta(
        self, servicio_aprobado, horario_semanal, fecha_futura
    ):
        from django.contrib.auth import get_user_model

        primera, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="10:00",
            datos=_datos(),
        )
        segunda, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="13:00",
            datos=_datos(),
        )
        assert primera.organizacion_id == segunda.organizacion_id
        assert primera.organizacion.usuario_id == segunda.organizacion.usuario_id
        Usuario = get_user_model()
        assert Usuario.objects.filter(email="invitado@test.skilly").count() == 1

    def test_email_normalizado_en_minusculas(
        self, servicio_aprobado, horario_semanal, fecha_futura
    ):
        from django.contrib.auth import get_user_model

        reserva, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="10:00",
            datos=_datos(email="Mixto@Test.Skilly"),
        )
        Usuario = get_user_model()
        usuario = Usuario.objects.get(pk=reserva.organizacion.usuario_id)
        assert usuario.email == "mixto@test.skilly"

    def test_email_existente_se_enlaza_a_su_organizacion(
        self, servicio_aprobado, horario_semanal, fecha_futura, organizacion
    ):
        from django.contrib.auth import get_user_model

        reserva, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="10:00",
            datos=_datos(email=organizacion.email_contacto),
        )
        assert reserva.organizacion_id == organizacion.id
        Usuario = get_user_model()
        assert Usuario.objects.filter(email__iexact=organizacion.email_contacto).count() == 1

    def test_usuario_organizacion_sin_perfil_usa_rut_existente(
        self, servicio_aprobado, horario_semanal, fecha_futura, organizacion
    ):
        from django.contrib.auth import get_user_model

        Usuario = get_user_model()
        Usuario.objects.create_user(
            email="sinperfil@test.skilly",
            password="SinPerfil123!",
            tipo=Usuario.TIPO_ORGANIZACION,
        )
        reserva, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="10:00",
            datos=_datos(email="sinperfil@test.skilly", rut=organizacion.rut),
        )
        assert reserva.organizacion_id == organizacion.id

    def test_email_de_profesional_no_crea_cuenta(
        self, servicio_aprobado, horario_semanal, fecha_futura, profesional
    ):
        from django.contrib.auth import get_user_model

        email = profesional.usuario.email
        reserva, _ = self._reservar(
            servicio=servicio_aprobado,
            fecha=fecha_futura,
            hora="10:00",
            datos=_datos(email=email),
        )
        assert reserva.organizacion.usuario_id is None
        Usuario = get_user_model()
        assert Usuario.objects.filter(email=email).count() == 1

    def test_envia_correo_de_activacion(
        self,
        servicio_aprobado,
        horario_semanal,
        fecha_futura,
        django_capture_on_commit_callbacks,
    ):
        from django.core import mail

        with django_capture_on_commit_callbacks(execute=True):
            reserva, _ = self._reservar(
                servicio=servicio_aprobado,
                fecha=fecha_futura,
                hora="10:00",
                datos=_datos(),
            )
        assert len(mail.outbox) == 1
        assert "/activar-cuenta/" in mail.outbox[0].alternatives[0][0]
        assert mail.outbox[0].to == ["invitado@test.skilly"]

    def test_envia_aviso_a_cuenta_existente(
        self,
        servicio_aprobado,
        horario_semanal,
        fecha_futura,
        organizacion,
        django_capture_on_commit_callbacks,
    ):
        from django.core import mail

        with django_capture_on_commit_callbacks(execute=True):
            self._reservar(
                servicio=servicio_aprobado,
                fecha=fecha_futura,
                hora="10:00",
                datos=_datos(email=organizacion.email_contacto),
            )
        assert len(mail.outbox) == 1
        assert "reserva" in mail.outbox[0].subject.lower()
        assert mail.outbox[0].to == [organizacion.email_contacto]


@pytest.mark.django_db
class TestMaquinaDeEstados:
    def test_flujo_completo(self, reserva_pendiente, profesional):
        services.aceptar(reserva_pendiente, profesional.usuario)
        assert reserva_pendiente.estado == Reserva.ESTADO_EN_CURSO

        services.marcar_entregado(reserva_pendiente, profesional.usuario)
        assert reserva_pendiente.estado == Reserva.ESTADO_ENTREGADO_POR_CONFIRMAR

        services.confirmar_entrega(reserva_pendiente)
        assert reserva_pendiente.estado == Reserva.ESTADO_FINALIZADA

        tipos = list(
            reserva_pendiente.eventos.values_list("tipo", flat=True)
        )
        assert tipos == [
            EventoReserva.TIPO_CREADA,
            EventoReserva.TIPO_ACEPTADA,
            EventoReserva.TIPO_ENTREGADA,
            EventoReserva.TIPO_CONFIRMADA,
        ]

    def test_no_acepta_dos_veces(self, reserva_pendiente):
        services.aceptar(reserva_pendiente)
        with pytest.raises(ValidationError):
            services.aceptar(reserva_pendiente)

    def test_rechazar_marca_cancelada(self, reserva_pendiente, profesional):
        services.rechazar(reserva_pendiente, profesional.usuario, "No puedo esa fecha.")
        assert reserva_pendiente.estado == Reserva.ESTADO_CANCELADA
        assert reserva_pendiente.motivo_rechazo == "No puedo esa fecha."

    def test_reporte_de_problema_crea_disputa(self, reserva_pendiente, organizacion):
        services.aceptar(reserva_pendiente, reserva_pendiente.profesional.usuario)
        services.reportar_problema(
            reserva_pendiente, organizacion.usuario, "No cumplió", "Faltó la mitad."
        )
        assert reserva_pendiente.estado == Reserva.ESTADO_CON_DISPUTA
        assert reserva_pendiente.disputa.motivo == "No cumplió"

    def test_monto_neto_descuenta_comision(self, reserva_pendiente):
        # tasa por defecto 10%
        assert str(reserva_pendiente.monto_neto) == "135000.00"


@pytest.mark.django_db
class TestReembolso:
    def _reserva_en(self, fecha, hora="10:00"):
        from datetime import time

        from apps.catalogo.models import Servicio
        from apps.usuarios.models import Organizacion, Profesional

        servicio = Servicio.objects.first()
        return Reserva.objects.create(
            servicio=servicio,
            profesional=servicio.profesional,
            organizacion=Organizacion.objects.first(),
            fecha=fecha,
            hora_inicio=time.fromisoformat(hora),
            hora_fin="13:00",
            precio_acordado=100000,
            formato=Servicio.FORMATO_REMOTO,
            contacto_nombre="X",
            contacto_email="x@test.skilly",
        )

    def test_sin_penalidad_con_24h_o_mas(self, reserva_pendiente):
        from datetime import date

        ahora = services.aware(date(2026, 1, 8), __import__("datetime").time(10, 0))
        reserva = self._reserva_en(date(2026, 1, 10))
        assert services.porcentaje_reembolso(reserva, ahora=ahora) == 100

    def test_penalidad_tardia_bajo_24h(self, reserva_pendiente):
        from datetime import date, time

        ahora = services.aware(date(2026, 1, 9), time(20, 0))
        reserva = self._reserva_en(date(2026, 1, 10))
        assert services.porcentaje_reembolso(reserva, ahora=ahora) == 90


@pytest.mark.django_db
class TestVencimiento:
    def test_expira_pendientes_vencidas(self, reserva_pendiente):
        reserva_pendiente.expira_en = timezone.now() - timedelta(minutes=1)
        reserva_pendiente.save(update_fields=["expira_en"])

        total = services.expirar_vencidas()

        reserva_pendiente.refresh_from_db()
        assert total == 1
        assert reserva_pendiente.estado == Reserva.ESTADO_VENCIDA

    def test_no_expira_aceptadas(self, reserva_pendiente):
        services.aceptar(reserva_pendiente)
        reserva_pendiente.expira_en = timezone.now() - timedelta(minutes=1)
        reserva_pendiente.save(update_fields=["expira_en"])

        assert services.expirar_vencidas() == 0
