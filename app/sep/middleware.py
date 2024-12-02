"""Define middleware to handle CSRF protection."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.sep.config import sep_settings
from app.sep.deps import CsrfProtectDep

templates = sep_settings.TEMPLATES


class CSRFMiddleware(BaseHTTPMiddleware):
    """Manage CSRF protection for HTTP requests and responses."""

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
        csrf_protect = CsrfProtectDep()
        csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
        request.state.csrf_token = csrf_token
        request.state.signed_token = signed_token
        response = await call_next(request)

        csrf_protect.set_csrf_cookie(signed_token, response)

        if hasattr(response, "context"):
            response.context["csrf_token"] = csrf_token

        return response
