"""Define middleware to handle CSRF protection."""

from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class CSRFMiddleware(BaseHTTPMiddleware):
    """Manage CSRF protection for HTTP requests and responses."""

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
        method = request.method.upper()

        if method == "GET":
            csrf_token, signed_token = self.csrf_protect.generate_csrf_tokens()
            request.state.csrf_token = csrf_token

        response = await call_next(request)

        endpoint = request.scope.get("endpoint")
        if not isinstance(endpoint, StaticFiles) and not getattr(
            request.state, "is_csrf_exempt", False
        ):
            csrf_cookie_handler = {
                "GET": lambda: self.csrf_protect.set_csrf_cookie(
                    signed_token, response
                ),
                "POST": lambda: self.csrf_protect.unset_csrf_cookie(response),
            }
            csrf_cookie_handler.get(method, lambda: None)()

        return response
