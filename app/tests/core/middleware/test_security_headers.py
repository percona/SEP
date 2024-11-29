"""Define tests for the app.core.middleware.security_headers module."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.core.middleware.security_headers import (
    PermissionsPolicyDirective,
    PermissionsPolicyOptions,
    SecurityHeadersMiddleware,
    SecurityHeadersOptions,
    StrictTransportSecurityOptions,
)


def create_test_app(options: SecurityHeadersOptions | None = None) -> FastAPI:
    """Create a test FastAPI app with the SecurityHeadersMiddleware applied.

    :param options: The SecurityHeadersOptions for the SecurityHeadersMiddleware, if
        any.
    :type options: SecurityHeadersOptions | None
    :return: The test FastAPI app.
    :rtype: FastAPI
    """
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, options=options)

    @app.get("/")
    async def read_root(request: Request):
        nonce = getattr(request.state, "csp_nonce", None)
        return PlainTextResponse(f"Nonce: {nonce}")

    return app


@pytest.fixture
def test_client() -> TestClient:
    """Provide a test client for the app with the default SecurityHeadersMiddleware."""
    return TestClient(create_test_app())


class TestPermissionsPolicyOptions:
    """Define test suite for PermissionsPolicyOptions."""

    def test_validation_error(self):
        """Test that a ValueError is raised when directives overlap."""
        with pytest.raises(
            ValueError, match="Directives cannot be in both allow_self and allow_all"
        ):
            PermissionsPolicyOptions(
                allow_self={PermissionsPolicyDirective.CAMERA},
                allow_all={PermissionsPolicyDirective.CAMERA},
            )

    def test_header_generation(self):
        """Test that the header property generates the correct Permissions-Policy."""
        options = PermissionsPolicyOptions(
            allow_self={
                PermissionsPolicyDirective.CAMERA,
                PermissionsPolicyDirective.MICROPHONE,
            },
            allow_all={PermissionsPolicyDirective.GEOLOCATION},
        )
        header = options.header

        assert "camera=(self)" in header
        assert "microphone=(self)" in header
        assert "geolocation=*" in header

        denied_directives = (
            set(PermissionsPolicyDirective) - options.allow_self - options.allow_all
        )
        for directive in denied_directives:
            assert f"{directive}=()" in header


class TestStrictTransportSecurityOptions:
    """Define test suite for StrictTransportSecurityOptions."""

    def test_header_generation(self):
        """Test that the header property generates the correct HSTS header."""
        options = StrictTransportSecurityOptions(
            max_age=31536000, include_sub_domains=True, preload=True
        )
        header = options.header
        expected_header = "max-age=31536000; includeSubDomains; preload"
        assert header == expected_header

        # Test without include_sub_domains and preload
        options = StrictTransportSecurityOptions(max_age=86400)
        header = options.header
        expected_header = "max-age=86400"
        assert header == expected_header


class TestSecurityHeadersMiddleware:
    """Define test suite for SecurityHeadersMiddleware."""

    def test_default_options(self, test_client):
        """Test that default options add the correct security headers."""
        response = test_client.get("/")
        headers = response.headers

        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "same-origin"
        assert "Strict-Transport-Security" not in headers
        assert "Content-Security-Policy" in headers
        assert "Permissions-Policy" in headers

        csp_header = headers["Content-Security-Policy"]
        assert "script-src 'nonce-" in csp_header

    def test_custom_options(self):
        """Test that custom configuration options are respected."""
        options = SecurityHeadersOptions(
            x_frame_options_deny=False,
            x_content_type_options_nosniff=False,
            referrer_policy_same_origin=False,
            strict_transport_security=StrictTransportSecurityOptions(
                max_age=63072000, include_sub_domains=True, preload=True
            ),
            content_security_policy_strict=False,
            permissions_policy=PermissionsPolicyOptions(
                allow_all={PermissionsPolicyDirective.GEOLOCATION}
            ),
        )
        app = create_test_app(options)
        client = TestClient(app)
        response = client.get("/")
        headers = response.headers

        assert "X-Frame-Options" not in headers
        assert "X-Content-Type-Options" not in headers
        assert "Referrer-Policy" not in headers
        assert (
            headers["Strict-Transport-Security"]
            == "max-age=63072000; includeSubDomains; preload"
        )
        assert "Content-Security-Policy" not in headers
        assert "Permissions-Policy" in headers

        permissions_policy_header = headers["Permissions-Policy"]
        assert "geolocation=*" in permissions_policy_header
        denied_directives = (
            set(PermissionsPolicyDirective) - options.permissions_policy.allow_all
        )
        for directive in denied_directives:
            assert f"{directive}=()" in permissions_policy_header

    def test_csp_nonce(self, test_client):
        """Test that CSP nonce is set when content_security_policy_strict is True."""
        response = test_client.get("/")
        headers = response.headers

        csp_header = headers["Content-Security-Policy"]
        nonce_match = re.search(r"script-src 'nonce-([^']+)'", csp_header)
        assert nonce_match is not None
        nonce_in_header = nonce_match.group(1)
        assert response.text == f"Nonce: {nonce_in_header}"

    def test_no_csp(self):
        """Test that CSP is not set when content_security_policy_strict is False."""
        options = SecurityHeadersOptions(content_security_policy_strict=False)
        app = create_test_app(options)
        client = TestClient(app)
        response = client.get("/")
        headers = response.headers

        assert "Content-Security-Policy" not in headers
        assert response.text == "Nonce: None"
