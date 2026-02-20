"""Define tests for the app.core.auth.providers.casdoor module."""

from pydantic import SecretStr

from app.core.auth.providers.casdoor import CasdoorSDK


def test_casdoor_credentials_masked_in_repr():
    """Test that client_id and client_secret are masked in repr."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id=SecretStr("my-client-id"),
        client_secret=SecretStr("my-client-secret"),
    )
    repr_str = repr(sdk)
    assert "my-client-id" not in repr_str
    assert "my-client-secret" not in repr_str


def test_casdoor_api_key_decodes_secret_values():
    """Test that api_key correctly encodes the secret credentials."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id=SecretStr("test-id"),
        client_secret=SecretStr("test-secret"),
    )
    import base64

    expected = base64.b64encode(b"test-id:test-secret").decode("utf-8")
    assert sdk.api_key == expected
