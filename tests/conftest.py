import pytest

from snowth_my_net.logs import REDACTOR


@pytest.fixture(autouse=True)
def _forget_secrets():
    yield
    REDACTOR.clear()
