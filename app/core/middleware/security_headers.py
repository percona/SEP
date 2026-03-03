# Copyright 2025 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define the SecurityHeadersMiddleware and its associated models and options."""

from enum import StrEnum
from secrets import token_urlsafe
from typing import Annotated, Self

from annotated_types import Gt
from pydantic import model_validator
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EnumFieldMixin, URIPath


class PermissionsPolicyDirective(EnumFieldMixin, StrEnum):
    """Enumerate possible directives for the Permissions Policy.

    Each member represents a specific feature that can be controlled via the
    Permissions Policy header.
    """

    ACCELEROMETER = "accelerometer"
    AMBIENT_LIGHT_SENSOR = "ambient-light-sensor"
    ATTRIBUTION_REPORTING = "attribution-reporting"
    AUTOPLAY = "autoplay"
    BLUETOOTH = "bluetooth"
    BROWSING_TOPICS = "browsing-topics"
    CAMERA = "camera"
    COMPUTE_PRESSURE = "compute-pressure"
    DISPLAY_CAPTURE = "display-capture"
    DOCUMENT_DOMAIN = "document-domain"
    ENCRYPTED_MEDIA = "encrypted-media"
    FULLSCREEN = "fullscreen"
    GAMEPAD = "gamepad"
    GEOLOCATION = "geolocation"
    GYROSCOPE = "gyroscope"
    HID = "hid"
    IDENTITY_CREDENTIALS_GET = "identity-credentials-get"
    IDLE_DETECTION = "idle-detection"
    LOCAL_FONTS = "local-fonts"
    MAGNETOMETER = "magnetometer"
    MICROPHONE = "microphone"
    MIDI = "midi"
    OTP_CREDENTIALS = "otp-credentials"
    PAYMENT = "payment"
    PICTURE_IN_PICTURE = "picture-in-picture"
    PUBLICKEY_CREDENTIALS_CREATE = "publickey-credentials-create"
    PUBLICKEY_CREDENTIALS_GET = "publickey-credentials-get"
    SCREEN_WAKE_LOCK = "screen-wake-lock"
    SERIAL = "serial"
    SPEAKER_SELECTION = "speaker-selection"
    STORAGE_ACCESS = "storage-access"
    USB = "usb"
    WEB_SHARE = "web-share"
    WINDOW_MANAGEMENT = "window-management"
    XR_SPATIAL_TRACKING = "xr-spatial-tracking"


class PermissionsPolicyOptions(BaseCaseInsensitiveModel):
    """Configure the Permissions Policy header settings.

    :param allow_self: Set of directives that allow access from the same origin.
        Defaults to an empty set.
    :type allow_self: set[PermissionsPolicyDirective]
    :param allow_all: Set of directives that allow access from any origin. Defaults to
        an empty set.
    :type allow_all: set[PermissionsPolicyDirective]
    """

    allow_self: set[PermissionsPolicyDirective] = set()
    allow_all: set[PermissionsPolicyDirective] = set()

    @model_validator(mode="after")
    def validate_no_intersection(self) -> Self:
        """Ensure that no directives are present in both `allow_self` and `allow_all`.

        :return: The validated `PermissionsPolicyOptions` instance.
        :rtype: PermissionsPolicyOptions
        :raises ValueError: If any directives are found in both `allow_self` and
            `allow_all`.
        """
        if intersection := self.allow_self & self.allow_all:
            raise ValueError(
                f"Directives cannot be in both allow_self and allow_all: {intersection}"
            )
        return self

    @property
    def header(self) -> str:
        """Generate the header string based on the configured directives.

        :return: The formatted Permissions Policy header.
        :rtype: str
        """
        policy = ", ".join(f"{directive}=(self)" for directive in self.allow_self)
        policy += ", ".join(f"{directive}=*" for directive in self.allow_all)
        return policy + ", ".join(
            f"{directive}=()"
            for directive in set(PermissionsPolicyDirective)
            - self.allow_self
            - self.allow_all
        )


class StrictTransportSecurityOptions(BaseCaseInsensitiveModel):
    """Configure the Strict Transport Security (HSTS) header settings.

    :param max_age: Maximum age (in seconds) for the HSTS policy.
    :type max_age: int
    :param include_sub_domains: Whether to apply the HSTS policy to all subdomains.
        Defaults to False.
    :type include_sub_domains: bool
    :param preload: Whether to include the `preload` directive for HSTS. Defaults to
        False.
    :type preload: bool
    """

    max_age: Annotated[int, Gt(0)]
    include_sub_domains: bool = False
    preload: bool = False

    @property
    def header(self) -> str:
        """Generate the HSTS header string based on the configured options.

        :return: The formatted Strict Transport Security header.
        :rtype: str
        """
        hsts = f"max-age={self.max_age}"
        if self.include_sub_domains:
            hsts += "; includeSubDomains"
        if self.preload:
            hsts += "; preload"
        return hsts


class SecurityHeadersOptions(BaseCaseInsensitiveModel):
    """Configure various security headers for HTTP responses.

    :param x_frame_options_deny: Whether to set `X-Frame-Options` to `DENY`. Defaults to
        True.
    :type x_frame_options_deny: bool
    :param x_content_type_options_nosniff: Whether to set `X-Content-Type-Options` to
        `nosniff`. Defaults to True.
    :type x_content_type_options_nosniff: bool
    :param referrer_policy_same_origin: Whether to set `Referrer-Policy` to
        `same-origin`. Defaults to True.
    :type referrer_policy_same_origin: bool
    :param strict_transport_security: Configuration options for the
        `Strict-Transport-Security` header. Defaults to `None`, which omits the header.
    :type strict_transport_security: StrictTransportSecurityOptions | None
    :param content_security_policy_strict: Whether to enforce a strict Content Security
        Policy.
    :type content_security_policy_strict: bool
    :param content_security_policy_exclude_paths: List of URI paths to not include the
        CSP header.
    :type content_security_policy_exclude_paths: list[URIPath]
    :param permissions_policy: Configuration options for the `Permissions-Policy`
        header. Defaults to denying access to all directives.
    :type permissions_policy: PermissionsPolicyOptions
    """

    x_frame_options_deny: bool = True
    x_content_type_options_nosniff: bool = True
    referrer_policy_same_origin: bool = True
    strict_transport_security: StrictTransportSecurityOptions | None = None
    content_security_policy_strict: bool = True
    content_security_policy_exclude_paths: list[URIPath] = []
    permissions_policy: PermissionsPolicyOptions = PermissionsPolicyOptions()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security-related HTTP headers to responses.

    This middleware injects various security headers such as `X-Frame-Options`,
    `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security`,
    `Content-Security-Policy`, and `Permissions-Policy` based on the provided
    configuration options.

    :param app: The ASGI application to wrap with the middleware.
    :type app: ASGIApp
    :param options: Configuration options for setting security headers.
    :type options: SecurityHeadersOptions | None
    """

    def __init__(
        self, app: ASGIApp, options: SecurityHeadersOptions | None = None
    ) -> None:
        super().__init__(app)
        options = SecurityHeadersOptions() if options is None else options
        self.options = options
        self.security_headers = {}
        if options.x_frame_options_deny:
            self.security_headers["X-Frame-Options"] = "DENY"
        if options.x_content_type_options_nosniff:
            self.security_headers["X-Content-Type-Options"] = "nosniff"
        if options.referrer_policy_same_origin:
            self.security_headers["Referrer-Policy"] = "same-origin"
        if options.strict_transport_security is not None:
            self.security_headers["Strict-Transport-Security"] = (
                options.strict_transport_security.header
            )
        if options.permissions_policy is not None:
            self.security_headers["Permissions-Policy"] = (
                options.permissions_policy.header
            )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the incoming request and add security headers to the response.

        If `Content-Security-Policy` is enabled, generate a nonce for inline scripts and
        include it in the policy.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next middleware or endpoint in the ASGI application.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response with added security headers.
        :rtype: Response
        """
        extra_headers = {}
        if (
            self.options.content_security_policy_strict
            and request.url.path
            not in self.options.content_security_policy_exclude_paths
        ):
            nonce = token_urlsafe(32)
            request.state.csp_nonce = nonce
            extra_headers["Content-Security-Policy"] = (
                f"script-src 'nonce-{nonce}' 'strict-dynamic'; object-src 'none'; "
                f"base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        response = await call_next(request)
        for header, value in (self.security_headers | extra_headers).items():
            response.headers.setdefault(header, value)
        return response
