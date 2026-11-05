import pytest

from apps.pagos.seguridad import token_corto


@pytest.mark.pagos
class TestTokenCorto:
    def test_muestra_solo_prefijo(self):
        assert token_corto("abcdefghij") == "abcdef…"

    def test_token_vacio(self):
        assert token_corto("") == ""
        assert token_corto(None) == ""
