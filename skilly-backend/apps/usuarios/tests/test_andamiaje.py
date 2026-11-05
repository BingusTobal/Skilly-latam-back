"""
Pruebas del andamiaje. Tickets 0.5, 0.6, 0.9, 0.14.

Cada prueba fija una regla del Sprint 0 para que nadie la revierta por error.
"""
import pytest
from django.conf import settings


class TestZonaHoraria:
    """0.5: el calculo de slots (3.1) depende de esto."""

    def test_usa_tz_esta_activo(self):
        assert settings.USE_TZ is True

    def test_zona_horaria_de_negocio(self):
        assert settings.TIME_ZONE == "America/Santiago"


class TestConstantesDeNegocio:
    """0.9: los defaults aprobados en CONTEXTO-ARQUITECTURA.docx."""

    def test_plazo_respuesta_profesional(self):
        # R12: 12 horas (decision Sprint 4; antes 6)
        assert settings.PLAZO_RESPUESTA_PROFESIONAL_HORAS == 12

    def test_recordatorio_antes_de_vencer(self):
        # R12: recordatorio en T0+4h, antes del vencimiento
        assert settings.PLAZO_RECORDATORIO_HORAS < settings.PLAZO_RESPUESTA_PROFESIONAL_HORAS

    def test_margen_y_anticipacion_de_reserva(self):
        # Sprint 4: min(ahora + 12 h, inicio - 3 h) y reserva con 12 h de aviso
        assert settings.HORAS_MARGEN_RESPUESTA == 3
        assert settings.HORAS_ANTICIPACION_MINIMA_RESERVA == 12

    def test_ventana_de_pago_pendiente(self):
        # Sprint 4: la reserva bloquea el horario 15 min mientras se paga
        assert settings.MINUTOS_PAGO_PENDIENTE == 15

    def test_plazo_revision_organizacion(self):
        # R18: auto liberacion a los 5 dias
        assert settings.PLAZO_REVISION_ORGANIZACION_DIAS == 5

    def test_ventana_autorizacion_webpay(self):
        # 4.9: ~7 dias, con re-autorizacion
        assert settings.DIAS_VENTANA_AUTORIZACION_WEBPAY == 7

    def test_token_magico_dura_24h(self):
        # D7
        assert settings.TOKEN_MAGICO_HORAS == 24

    def test_monto_minimo_servicio(self):
        assert settings.MONTO_MINIMO_SERVICIO == 5000

    def test_tasa_comision_defecto(self):
        assert 0 < settings.TASA_COMISION_DEFECTO < 1

    def test_penalidad_cancelacion(self):
        # D3: 100% hasta 24h antes del kickoff
        assert settings.HORAS_CANCELACION_SIN_PENALIDAD == 24
        assert settings.PORCENTAJE_REEMBOLSO_CANCELACION_TARDIA == 90

    def test_solo_tres_formatos(self):
        # R5
        assert settings.FORMATOS_EJECUCION == ("remoto", "presencial", "hibrido")


class TestCORS:
    """0.6: nunca comodines con credenciales."""

    def test_lista_blanca_de_origenes(self):
        assert isinstance(settings.CORS_ALLOWED_ORIGINS, list)

    def test_sin_comodin_con_credenciales(self):
        if settings.CORS_ALLOW_CREDENTIALS:
            assert "*" not in settings.CORS_ALLOWED_ORIGINS


class TestHealthCheck:
    """0.14"""

    def test_health_responde_ok(self, client, db):
        respuesta = client.get("/health/")
        assert respuesta.status_code == 200
        assert respuesta.json()["base_datos"] == "ok"
        assert respuesta.json()["servicio"] == "skilly-latam"

    def test_health_es_publico(self, anon_client, db):
        """No debe pedir autenticacion: lo consume el balanceador."""
        assert anon_client.get("/health/").status_code == 200


class TestJWTSeguro:
    """0.17: rotacion y blacklist habilitados."""

    def test_rotacion_de_refresh(self):
        assert settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"] is True

    def test_blacklist_tras_rotacion(self):
        assert settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"] is True


class TestFormatoEjecucion:
    """R5: los tres formatos permitidos."""

    @pytest.mark.parametrize("formato", ["remoto", "presencial", "hibrido"])
    def test_formatos_validos(self, formato):
        assert formato in settings.FORMATOS_EJECUCION

    def test_formato_invalido(self):
        assert "hibrido_remoto" not in settings.FORMATOS_EJECUCION