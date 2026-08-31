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
"""Resolve the side-car's Grafana service-account token before supervisord starts.

``entrypoint.sh`` runs this once, after ``settings-env.sh`` has expanded the
deployment inputs and before it execs supervisord, and captures stdout. Stdout
carries the resolved token and nothing else; every diagnostic goes to stderr.
Printing nothing means there was nothing to resolve: a token already
configured, a provider other than Grafana, or settings that did not
resolve. None of those is a failure.

Configuration is read from the application's own settings classes rather than
re-derived, so the endpoint, the TLS setting and the two canonical token names
consulted here are the ones the five supervised programs will read. Unlike the
build-time helpers beside it, this one runs where ``bundle.tgz`` has already put
``app/`` on the path.

Deployment inputs, all optional: ``GF_SECURITY_ADMIN_USER`` and
``GF_SECURITY_ADMIN_PASSWORD`` (each defaulting to Grafana's own ``admin``),
``SEP_STATE_DIR`` and ``SEP_GRAFANA_MINT_TIMEOUT``.
"""

import asyncio
import logging
import math
import os
import secrets
import sys
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager, redirect_stdout
from enum import StrEnum
from pathlib import Path

from aiohttp import ClientError
from fastapi import HTTPException, status

from app.core.auth.providers.grafana.sdk import GrafanaSDK
from app.core.config import settings
from app.core.requests.connectivity import PROBE_TIMEOUT_SECONDS
from app.core.requests.remote_api import RemoteAPI
from app.core.utils.date_time import utc_now
from app.core.utils.strings import b64encode_str

SERVICE_ACCOUNT_NAME = "sep"
SERVICE_ACCOUNT_ROLE = "Admin"

DEFAULT_STATE_DIR = Path("/home/sep/state")
PERSISTED_FILENAME = "grafana_service_account_token"

DEFAULT_MINT_TIMEOUT_SECONDS = 60.0
RETRY_INTERVAL_SECONDS = 3.0

DEFAULT_ADMIN_CREDENTIAL = "admin"

VALIDATION_PATH = "/api/org/users"
SERVICE_ACCOUNTS_PATH = "/api/serviceaccounts"
SERVICE_ACCOUNT_SEARCH_PATH = "/api/serviceaccounts/search"

RETRYABLE_STATUSES = frozenset(
    {
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        status.HTTP_504_GATEWAY_TIMEOUT,
    }
)
"""What a Grafana still starting behind PMM's proxy answers.

Every other status is a deterministic fault — a wrong admin credential, a
misconfigured endpoint, a body Grafana refuses — which a retry can only
repeat until the bound runs out, delaying the actionable message by the
whole budget.
"""


class MintError(Exception):
    """Raise when no token can be minted and the pre-flight has to give up."""


class TokenStateEnum(StrEnum):
    """Name what Grafana answered about a token SEP already holds."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FORBIDDEN = "forbidden"
    UNREACHABLE = "unreachable"


def warn(message: str) -> None:
    """Write one diagnostic line, leaving stdout as the token channel alone.

    :param message: The line to write.
    """
    sys.stderr.write(f"[grafana-mint] {message}\n")


def admin_credentials() -> str:
    """Return the Base64 admin pair the mint calls authenticate with.

    Each half falls back to Grafana's own bootstrap default when unset or blank,
    which is what the paired stack runs at.

    :return: The Base64 ``user:password`` pair.
    """
    user = os.environ.get("GF_SECURITY_ADMIN_USER") or ""
    password = os.environ.get("GF_SECURITY_ADMIN_PASSWORD") or ""
    if not user.strip():
        user = DEFAULT_ADMIN_CREDENTIAL
    if not password.strip():
        password = DEFAULT_ADMIN_CREDENTIAL
    return b64encode_str(f"{user}:{password}")


def state_dir() -> Path:
    """Return the directory SEP persists its minted token in.

    :return: The configured directory, or the image's own.
    """
    configured = os.environ.get("SEP_STATE_DIR") or ""
    return Path(configured) if configured.strip() else DEFAULT_STATE_DIR


def mint_timeout() -> float:
    """Return how long minting may keep retrying before it gives up.

    :return: The bound in seconds.
    """
    raw = (os.environ.get("SEP_GRAFANA_MINT_TIMEOUT") or "").strip()
    if not raw:
        return DEFAULT_MINT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if not math.isfinite(seconds) or seconds <= 0:
        warn(
            f"SEP_GRAFANA_MINT_TIMEOUT={raw!r} is not a finite positive number "
            f"of seconds; waiting {DEFAULT_MINT_TIMEOUT_SECONDS:g}s instead."
        )
        return DEFAULT_MINT_TIMEOUT_SECONDS
    return seconds


def read_persisted_token(directory: Path) -> str | None:
    """Return the token an earlier start persisted, if it left a usable one.

    :param directory: The state directory to read from.
    :return: The stripped token, or ``None`` when the file is absent,
        unreadable, or holds only whitespace.
    """
    try:
        raw = (directory / PERSISTED_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None
    return raw.strip() or None


def write_persisted_token(directory: Path, token: str) -> bool:
    """Persist ``token`` owner-only so the next start needs no admin credential.

    The value is written through a sibling temporary file so a start interrupted
    mid-write cannot leave a truncated token in place of a working one, and
    ``umask`` narrows the mode at creation so it is never briefly group-readable.
    The explicit ``chmod`` covers the case ``umask`` cannot: a temporary file an
    earlier start left behind is truncated rather than created, so it keeps
    whatever mode it already carried.

    :param directory: The state directory to write into, created when absent.
    :param token: The token to persist.
    :return: Whether the token was persisted.
    """
    temporary = directory / f".{PERSISTED_FILENAME}"
    previous_umask = os.umask(0o077)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(token, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(directory / PERSISTED_FILENAME)
    except OSError as error:
        warn(
            f"Could not persist the Grafana token under {directory}: {error}. "
            "The token serves this run, but the next start has to mint again."
        )
        return False
    finally:
        os.umask(previous_umask)
    return True


@contextmanager
def quiet_client_logging(api: RemoteAPI, floor: int) -> Generator[None]:
    """Hold the client's own logger at or above ``floor`` for the wrapped calls.

    Two reasons, both about what reaches ``docker logs``. ``RemoteAPI.request``
    logs the parsed response body at DEBUG, and the create-token response
    carries the minted token in its ``key`` field. And ``GrafanaSDK.request``
    logs a full traceback for every connection failure, which during a bounded
    wait for a Grafana that has not started yet repeats once per attempt,
    where this helper reports the same outcome once, on stderr, naming the
    endpoint and the classified cause.

    :param api: The client whose logger to hold.
    :param floor: The lowest level the logger may emit at meanwhile.
    :return: ``None`` while the floor is in force.
    """
    logger = api.logger
    configured_level = logger.level
    logger.setLevel(max(logger.getEffectiveLevel(), floor))
    try:
        yield
    finally:
        logger.setLevel(configured_level)


async def validate_token(provider: GrafanaSDK, token: str) -> TokenStateEnum:
    """Check what Grafana makes of a token SEP already holds.

    The call is bounded independently of the client's own pool timeouts, so a
    stalled Grafana costs one probe rather than the whole start path. A 403 is
    kept apart from a 401 because it means the token is valid and the account's
    org role is merely below ``Admin``, which re-minting cannot change.

    :param provider: The open Grafana client.
    :param token: The token to present.
    :return: What Grafana answered, classified.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            with provider.auth(token):
                await provider.get(VALIDATION_PATH)
    except HTTPException as error:
        if error.status_code == status.HTTP_401_UNAUTHORIZED:
            return TokenStateEnum.REJECTED
        if error.status_code == status.HTTP_403_FORBIDDEN:
            return TokenStateEnum.FORBIDDEN
        return TokenStateEnum.UNREACHABLE
    except (ClientError, TimeoutError):
        return TokenStateEnum.UNREACHABLE
    return TokenStateEnum.ACCEPTED


def token_name() -> str:
    """Return a token name no repeated or concurrent mint can collide with.

    The random suffix is what makes it unique: :func:`utc_now` zeroes
    microseconds and the format is second-granular anyway, so two mints in the
    same second would otherwise ask for the same name.

    :return: The token name.
    """
    return f"{SERVICE_ACCOUNT_NAME}-{utc_now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"


async def search_account(provider: GrafanaSDK) -> int | None:
    """Return the id of the service account named exactly ``sep``, if it exists.

    Grafana's ``query`` filters by substring, so the results are matched on the
    exact name: an unrelated ``sep-legacy`` account comes back for a ``sep``
    query, and minting onto it would be silent.

    :param provider: The open Grafana client, authenticated as the admin.
    :return: The account's id, or ``None`` when no exact match came back.
    :raises HTTPException: When Grafana answers an error status.
    :raises ClientError: When Grafana cannot be reached at all.
    """
    found = await provider.get(
        SERVICE_ACCOUNT_SEARCH_PATH, params={"query": SERVICE_ACCOUNT_NAME}
    )
    accounts = found.get("serviceAccounts") if isinstance(found, Mapping) else None
    for account in accounts if isinstance(accounts, list) else ():
        if (
            isinstance(account, Mapping)
            and account.get("name") == SERVICE_ACCOUNT_NAME
            and account.get("id") is not None
        ):
            return account["id"]
    return None


async def find_or_create_account(provider: GrafanaSDK) -> tuple[int, bool]:
    """Return the id of SEP's service account, creating it when absent.

    A refused creation is re-checked against a second lookup rather than
    reported: two side-cars starting together can both search before either
    creates, and the loser must mint on the account that won rather than fail.
    The lookup decides that, not the refusal's status, because Grafana's
    duplicate-name status varies by release.

    The second element is ``True`` when the id came from a search (initial or
    race-recovery) rather than a create this call performed.

    :param provider: The open Grafana client, authenticated as the admin.
    :return: The service account's id, and whether it was reused rather than
        created.
    :raises MintError: When Grafana creates an account but answers no id.
    :raises HTTPException: When Grafana refuses the creation and no account of
        that name exists afterwards.
    :raises ClientError: When Grafana cannot be reached at all.
    """
    existing = await search_account(provider)
    if existing is not None:
        return existing, True
    try:
        created = await provider.post(
            SERVICE_ACCOUNTS_PATH,
            json={
                "name": SERVICE_ACCOUNT_NAME,
                "role": SERVICE_ACCOUNT_ROLE,
                "isDisabled": False,
            },
        )
    except HTTPException:
        winner = await search_account(provider)
        if winner is None:
            raise
        return winner, True
    account_id = created.get("id") if isinstance(created, Mapping) else None
    if account_id is None:
        raise MintError(
            f"Grafana answered no service-account id when creating "
            f"{SERVICE_ACCOUNT_NAME!r}; the response was a "
            f"{type(created).__name__}."
        )
    return account_id, False


async def mint(provider: GrafanaSDK, credentials: str) -> tuple[str, bool]:
    """Obtain a fresh service-account token from Grafana in one attempt.

    ``secondsToLive`` is left out of the request: Grafana reads its absence as
    "never expires", and an expiring token would strand the side-car holding a
    credential it cannot renew without the admin password.

    :param provider: The open Grafana client.
    :param credentials: The Base64 admin pair to authenticate with.
    :return: The minted token, and whether it was minted onto a reused account.
    :raises MintError: When Grafana answers a token response carrying no key, or
        creates an account but answers no id.
    :raises HTTPException: When Grafana answers an error status.
    :raises ClientError: When Grafana cannot be reached at all.
    """
    with (
        provider.auth(credentials, auth_scheme="Basic"),
        quiet_client_logging(provider, logging.INFO),
    ):
        account_id, reused = await find_or_create_account(provider)
        created = await provider.post(
            f"{SERVICE_ACCOUNTS_PATH}/{account_id}/tokens", json={"name": token_name()}
        )
    token = created.get("key") if isinstance(created, Mapping) else None
    if not isinstance(token, str) or not token.strip():
        raise MintError(
            f"Grafana answered no usable token key when creating a token on "
            f"service account {account_id}; the response was a "
            f"{type(created).__name__}."
        )
    return token.strip(), reused


async def mint_with_retry(
    provider: GrafanaSDK, credentials: str, deadline: float
) -> tuple[str, bool]:
    """Mint a token, retrying only what a still-starting Grafana explains.

    Each attempt carries its own timeout off ``deadline``: the client's session
    is opened with a 300 s total and offers no field to narrow it, so without
    the wrapper one stalled call would outlast the whole bound several times
    over.

    :param provider: The open Grafana client.
    :param credentials: The Base64 admin pair to authenticate with.
    :param deadline: The :func:`time.monotonic` reading to give up at.
    :return: The minted token, and whether it was minted onto a reused account.
    :raises MintError: When Grafana answers a fault no retry can clear, or when
        the deadline passes first.
    """
    started = time.monotonic()
    last_failure = "no attempt completed"
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            async with asyncio.timeout(remaining):
                return await mint(provider, credentials)
        except HTTPException as error:
            if error.status_code not in RETRYABLE_STATUSES:
                raise _fatal_mint_error(provider, error) from None
            last_failure = f"HTTP {error.status_code}: {error.detail}"
        except (ClientError, TimeoutError) as error:
            last_failure = f"{type(error).__name__}: {error}"
        await asyncio.sleep(
            max(0.0, min(RETRY_INTERVAL_SECONDS, deadline - time.monotonic()))
        )
    raise MintError(
        f"Could not mint a Grafana service-account token at {provider.endpoint} "
        f"after waiting {time.monotonic() - started:.1f}s (last failure: "
        f"{last_failure}). SEP starts without Grafana-backed sign-in and "
        "without the PMM syncer."
    )


def _fatal_mint_error(provider: RemoteAPI, error: HTTPException) -> MintError:
    """Return an actionable message for a status no retry can clear.

    :param provider: The client whose endpoint answered.
    :param error: The upstream error to explain.
    :return: The error to raise.
    """
    if error.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        return MintError(
            f"Grafana at {provider.endpoint} rejected SEP's admin credential "
            f"(HTTP {error.status_code}). Set GF_SECURITY_ADMIN_USER and "
            "GF_SECURITY_ADMIN_PASSWORD to Grafana's current admin login."
        )
    if error.status_code == status.HTTP_404_NOT_FOUND:
        return MintError(
            f"Grafana's service-account API is not at {provider.endpoint} "
            "(HTTP 404). Check that the endpoint carries PMM's /graph prefix."
        )
    return MintError(
        f"Grafana at {provider.endpoint} refused the mint with HTTP "
        f"{error.status_code}: {error.detail}."
    )


def already_supplied(service_account_token: str, pmm_api_key: str) -> bool:
    """Return whether a token is already configured for either canonical name.

    A blank value counts as absent at every layer, which is why the profile's
    baked empty token does not read as a configured one.

    :param service_account_token: The resolved Grafana service-account token.
    :param pmm_api_key: The resolved ``PMM.API_KEY``.
    :return: Whether minting must be skipped.
    """
    return bool(service_account_token.strip() or pmm_api_key.strip())


def resolve_provider() -> GrafanaSDK | None:
    """Return the Grafana client to resolve a token through, if there is one.

    Answers ``None`` for each case with nothing to do: settings that did not
    resolve, a provider other than Grafana, and a token already configured under
    either canonical name.

    :return: The open-able Grafana provider, or ``None``.
    """
    try:
        # import-time-settings: `auth_settings = AuthSettings()` runs at import
        # of app.core.auth.config, and the provider module reads
        # settings.SECRET_KEY at import to derive its assertion key. Both raise
        # on a profile that does not validate, and the five supervised programs
        # report that with far better context — so a settings problem must not
        # become a container that never starts.
        from app.core.auth.config import auth_settings
        from app.core.auth.providers.grafana.provider import GrafanaAuthProvider

        provider = auth_settings.active_provider
        pmm_api_key = settings.PMM.api_key
    except Exception as error:  # noqa: BLE001 -- reported, never re-raised
        warn(
            "Skipping the Grafana token pre-flight: settings did not resolve "
            f"({type(error).__name__}). The supervised programs report why."
        )
        return None
    if not isinstance(provider, GrafanaAuthProvider):
        return None
    if already_supplied(
        provider.service_account_token.get_secret_value(),
        pmm_api_key.get_secret_value() if pmm_api_key else "",
    ):
        return None
    return provider


async def keep_persisted_token(provider: GrafanaSDK, token: str) -> bool:
    """Return whether Grafana's answer leaves the persisted token usable.

    :param provider: The open Grafana client.
    :param token: The token an earlier start persisted.
    :return: Whether to keep it rather than mint a replacement.
    """
    state = await validate_token(provider, token)
    if state is TokenStateEnum.FORBIDDEN:
        warn(
            f"Grafana accepts the persisted token but the "
            f"{SERVICE_ACCOUNT_NAME!r} service account ranks below "
            f"{SERVICE_ACCOUNT_ROLE} in its org; a re-mint would carry the same "
            "role, so the token is kept."
        )
    elif state is TokenStateEnum.UNREACHABLE:
        warn(
            f"Could not reach Grafana at {provider.endpoint} to revalidate "
            "SEP's persisted token; using it unvalidated."
        )
    return state is not TokenStateEnum.REJECTED


async def resolve_token() -> str | None:
    """Resolve the token for the three ranks below the mounted secrets channel.

    When a token is minted onto a reused service account, the token is probed
    with :func:`validate_token`. A ``FORBIDDEN`` answer means the account's
    org role ranks below ``Admin``; a diagnostic is written and the token is
    still returned, because a re-mint cannot raise the role.

    :return: The resolved token, or ``None`` when there is nothing to resolve.
    :raises MintError: When a token is needed and cannot be minted.
    """
    provider = resolve_provider()
    if provider is None:
        return None

    directory = state_dir()
    persisted = read_persisted_token(directory)
    deadline = time.monotonic() + mint_timeout()
    with quiet_client_logging(provider, logging.CRITICAL):
        async with provider:
            if persisted is not None and await keep_persisted_token(
                provider, persisted
            ):
                return persisted
            token, reused = await mint_with_retry(
                provider, admin_credentials(), deadline
            )
            if reused:
                probe = await validate_token(provider, token)
                if probe is TokenStateEnum.FORBIDDEN:
                    warn(
                        f"Grafana accepts the freshly minted token but the "
                        f"{SERVICE_ACCOUNT_NAME!r} service account ranks below "
                        f"{SERVICE_ACCOUNT_ROLE} in its org; a re-mint would carry "
                        "the same role, so the token is kept."
                    )
    write_persisted_token(directory, token)
    return token


def main() -> int:
    """Print the resolved token for ``entrypoint.sh`` to capture.

    :return: The process exit status.
    """
    try:
        # The settings stack applies its logging configuration on first access,
        # binding handlers to whatever stdout is then -- so without this every
        # log record would land inside the token entrypoint.sh captures.
        with redirect_stdout(sys.stderr):
            token = asyncio.run(resolve_token())
    except MintError as error:
        warn(str(error))
        return 1
    if token:
        sys.stdout.write(f"{token}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
