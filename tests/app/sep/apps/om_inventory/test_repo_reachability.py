# Copyright (C) 2026 Percona LLC
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

"""Test whether a host can reach Percona's repository, and why not when it cannot.

This is an install and upgrade precondition, so the failures worth catching are the
ones that pass a cheaper check. A ping succeeds through a proxy that blocks this
origin; a TCP connect succeeds against a TLS interception appliance whose certificate
the host does not trust; a status-code check succeeds against a captive portal
answering 200 with its own HTML. Each of those fails ``yum install`` and each has a
test here, because "reachable" meaning three different things is how this feature
would quietly stop being worth anything.

The proxy in effect is asserted too. Without it the result is unexplainable: a
refused connection from a host with no proxy and from a host behind a broken one are
the same string and completely different jobs.
"""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from app.sep.apps.om_inventory.payload.probe import (
    collect_repo_facts,
    DEFAULT_REPO_URL,
    PACKAGING_KEY_MARKER,
)

KEY_BODY = PACKAGING_KEY_MARKER + b"\nVersion: GnuPG v2\n\nmQINBF..."
HTTP_OK = 200
HTTP_FORBIDDEN = 403
SHORT_TIMEOUT = 3
PROXY = "http://proxy.internal:3128"


def _response(body: bytes, status: int = 200) -> MagicMock:
    """Build a stand-in for the object ``urlopen`` returns.

    :param body: What reading it yields.
    :param status: Its HTTP status.
    :return: The context-manager mock.
    """
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestReachable:
    """The repository answers with what it should."""

    def test_a_real_key_is_reachable(self) -> None:
        """The ordinary case: the key comes back and the host can install."""
        with patch(
            "urllib.request.urlopen", return_value=_response(KEY_BODY)
        ) as urlopen:
            facts = collect_repo_facts({})

        assert facts["reachable"] is True
        assert facts["status_code"] == HTTP_OK
        assert facts["error"] is None
        assert facts["url"] == DEFAULT_REPO_URL
        assert urlopen.call_args.kwargs["timeout"] > 0

    def test_latency_is_reported_even_on_success(self) -> None:
        """A slow-but-working repository is worth seeing before it becomes a failure."""
        with patch("urllib.request.urlopen", return_value=_response(KEY_BODY)):
            facts = collect_repo_facts({})

        assert facts["latency_ms"] is not None
        assert facts["latency_ms"] >= 0


class TestFailuresCheaperChecksMiss:
    """Each of these passes a ping, a connect, or a status check, and fails yum."""

    def test_a_captive_portal_answering_200_is_not_reachable(self) -> None:
        """Something answered; it was not the repository.

        The failure a status-code-only check reports as success, and the most likely
        one in the corporate networks this exists to describe.
        """
        with patch(
            "urllib.request.urlopen",
            return_value=_response(b"<html>Authentication required</html>"),
        ):
            facts = collect_repo_facts({})

        assert facts["reachable"] is False
        assert facts["status_code"] == HTTP_OK
        assert "not the repository" in facts["error"]

    def test_a_proxy_forbidding_the_origin_is_reported_with_its_code(self) -> None:
        """CONNECT allowed, this origin blocked: reachable at the socket, not usable."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                DEFAULT_REPO_URL, HTTP_FORBIDDEN, "Forbidden", {}, None
            ),
        ):
            facts = collect_repo_facts({})

        assert facts["reachable"] is False
        assert facts["status_code"] == HTTP_FORBIDDEN
        assert "403" in facts["error"]

    def test_a_tls_failure_names_itself(self) -> None:
        """An untrusted interception certificate is a distinct, fixable cause."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                "certificate verify failed: unable to get local issuer certificate"
            ),
        ):
            facts = collect_repo_facts({})

        assert facts["reachable"] is False
        assert "certificate verify failed" in facts["error"]

    def test_a_timeout_is_a_result_not_an_exception(self) -> None:
        """A hung repository must produce a row, not lose the whole host record."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            facts = collect_repo_facts({})

        assert facts["reachable"] is False
        assert "TimeoutError" in facts["error"]
        assert facts["latency_ms"] is not None


class TestTheProxyIsReported:
    """Without it the result cannot be explained."""

    @pytest.mark.parametrize(
        "variable", ["https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"]
    )
    def test_every_spelling_is_read(self, monkeypatch, variable: str) -> None:
        """All four spellings matter: a host may set any of them and urllib honours all.

        :param monkeypatch: The environment patcher.
        :param variable: The proxy environment variable to set.
        """
        for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(variable, PROXY)

        with patch("urllib.request.urlopen", return_value=_response(KEY_BODY)):
            facts = collect_repo_facts({})

        assert facts["proxy"] == PROXY

    def test_no_proxy_is_reported_as_none_not_omitted(self, monkeypatch) -> None:
        """A direct connection has to be stated, or a failure has no context.

        :param monkeypatch: The environment patcher.
        """
        for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
            monkeypatch.delenv(name, raising=False)

        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            facts = collect_repo_facts({})

        assert "proxy" in facts
        assert facts["proxy"] is None


class TestConfiguration:
    """An air-gapped estate mirrors the repository somewhere else."""

    def test_the_url_is_configurable(self) -> None:
        """Checking the public repository on a mirrored estate reports every host broken."""
        mirror = "https://mirror.internal/percona/PERCONA-PACKAGING-KEY"

        with patch(
            "urllib.request.urlopen", return_value=_response(KEY_BODY)
        ) as urlopen:
            facts = collect_repo_facts({"repo_url": mirror})

        assert facts["url"] == mirror
        assert urlopen.call_args.args[0].full_url == mirror

    def test_the_timeout_is_configurable(self) -> None:
        """A slow mirror on a fast link is a different budget from the public one."""
        with patch(
            "urllib.request.urlopen", return_value=_response(KEY_BODY)
        ) as urlopen:
            collect_repo_facts({"repo_timeout": SHORT_TIMEOUT})

        assert urlopen.call_args.kwargs["timeout"] == SHORT_TIMEOUT
