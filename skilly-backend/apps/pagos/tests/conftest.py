import pytest

from apps.pagos.gateway.fake import FakeGateway


@pytest.fixture(autouse=True)
def reset_fake_gateway():
    FakeGateway.reiniciar()
    yield
    FakeGateway.reiniciar()
