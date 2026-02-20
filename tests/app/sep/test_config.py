"""Define tests for the app.sep.config module."""

from pydantic import SecretStr

from app.sep.config import PMMSettings


def test_pmm_api_key_masked_in_repr():
    """Test that api_key is masked in repr output."""
    pmm = PMMSettings(api_key=SecretStr("my-pmm-api-key"))
    assert "my-pmm-api-key" not in repr(pmm)


def test_pmm_api_key_accepts_secretstr():
    """Test that PMMSettings accepts SecretStr for api_key."""
    pmm = PMMSettings(api_key=SecretStr("test-key"))
    assert pmm.api_key.get_secret_value() == "test-key"
