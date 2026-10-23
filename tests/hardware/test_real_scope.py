"""Tests against the real scope (read-only). Run with: uv run pytest -m hardware"""

import pytest

from scope_gui.driver import ScopeDriver
from scope_gui.models import InstrumentSupport
from scope_gui.settings import to_visa_resource

pytestmark = pytest.mark.hardware


def test_identity(scope_address):
    driver = ScopeDriver()
    try:
        identity = driver.connect(to_visa_resource(scope_address))
        assert identity.manufacturer == "LECROY"
        assert identity.model == "WR610ZI"
        assert identity.support is InstrumentSupport.SUPPORTED
    finally:
        driver.close()
