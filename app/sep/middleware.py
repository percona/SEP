"""Define middleware to handle CSRF protection."""

from fastapi_csrf_protect import CsrfProtect
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.sep.config import sep_settings

templates = sep_settings.TEMPLATES


class CSRFMiddleware(BaseHTTPMiddleware):
    """Manage CSRF protection for HTTP requests and responses."""

    EXCLUDED_PATHS = ("/static/", "/stream-logs/")

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.csrf_protect = CsrfProtect()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Add CSRF tokens to the request state and manage their inclusion in the response.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next middleware or endpoint in the ASGI application.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response with added security headers.
        :rtype: Response
        """
        if not self.is_relevant_request(request):
            return await call_next(request)

        method = request.method.upper()

        if method == "GET":
            csrf_token, signed_token = self.csrf_protect.generate_csrf_tokens()
            request.state.csrf_token = csrf_token

        response = await call_next(request)

        csrf_cookie_handler = {
            "GET": lambda: self.csrf_protect.set_csrf_cookie(signed_token, response),
            "POST": lambda: self.csrf_protect.unset_csrf_cookie(response),
        }
        csrf_cookie_handler.get(method, lambda: None)()

        return response

    def is_relevant_request(self, request: Request) -> bool:
        """Determine if the request should be handled by CSRF middleware."""
        return not request.url.path.startswith(self.EXCLUDED_PATHS)
