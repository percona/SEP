"""
SEP: Services Enablement Platform

Example config (JSON):
{
    "authz": {
        "backend": {
            "application_name": "<app-name>",
            "certificate": "<single-line-cert-as-string> | <env-var> | <file-path>",
            "client_id": "<client-id>",
            "client_secret": "<client-secret>",
            "endpoint": "<authz-endpoint>",
            "org_name": "<org-name>"
        },
        "config": {
            "backend_cookie": "<authz-cookie-name>",
            "redirect_uri": "<scheme>://<host>:<port>/api/signin",
            "secret_type": "inline | env | filesystem",
            "session_cookie": "<sesion-cookie-name>"
        }
    },
    "handlers": [
        ["/some-remote-app/", "sep.handlers.RemoteCallHandler", {"uri": "http://127.0.0.1:8282"}, ""],
        ["/some-app-with-config/(?P<route>jobs|deployments)?$", "someapp.Handler",
            {"host": "127.0.0.1", "secure": false, "timeout": 10, "verify": false, "cert": []}, "someapp"],
    ],
    "port": <port>
}
"""

__all__ = []
__version__ = "0.0.1"
