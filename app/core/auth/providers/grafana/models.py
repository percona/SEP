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

"""Define the Grafana user and token-payload models."""

import logging
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any, cast, Final, NoReturn, NotRequired, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, status
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import ConfigDict, model_validator, ValidationError, ValidationInfo
from pydantic.alias_generators import to_camel
from typing_extensions import TypedDict

from app.core.auth.models import (
    BaseTokenPayload,
    BaseUser,
    OAuthToken,
    SessionExchangeTokenResponse,
    UserRole,
)
from app.core.auth.providers.grafana.sdk import GrafanaException, GrafanaSDK
from app.core.config import settings
from app.core.exceptions import HTTPNotFoundException
from app.core.utils.fields import NonEmptyStr

logger = logging.getLogger(__name__)

ASSERTION_SALT: Final = "sep.auth.grafana.v1"

_TOKEN_SERIALIZER = URLSafeTimedSerializer(
    settings.SECRET_KEY.get_secret_value(), salt=ASSERTION_SALT
)


class _TokenType(StrEnum):
    """Define assertion ``typ`` claim values.

    An access token cannot be replayed at the refresh endpoint, nor a refresh
    token used as a Bearer credential. An exchange token is likewise refused at
    the refresh endpoint and on the session-cookie path; it is valid only as a
    Bearer credential.
    """

    ACCESS = "access"
    REFRESH = "refresh"
    EXCHANGE = "exchange"


# Tried in this order so the common access-token path costs a single signature
# check.
_BEARER_TOKEN_TYPES = (_TokenType.ACCESS, _TokenType.EXCHANGE)

_GRAFANA_ORG_ROLE_TO_USER_ROLE: Final[Mapping[str, UserRole]] = {
    "None": UserRole.NONE,
    "Viewer": UserRole.VIEWER,
    "Editor": UserRole.EDITOR,
    "Admin": UserRole.ADMIN,
}


def _rank_org_role(name: str | None) -> UserRole:
    """Return the SEP role a Grafana org role names.

    Grafana models "holds no role" as ``"None"`` or as an absent field, so both
    rank lowest without comment. A value Grafana does not define is schema
    drift instead: it also ranks lowest, because an unreadable membership
    proves no access, but it is logged so the drift stays visible rather than
    reading as a deliberate no-access decision.

    :param name: The ``role`` a Grafana record carries, if any.
    :return: The ranked ``UserRole``.
    """
    if name is None:
        return UserRole.NONE
    role = _GRAFANA_ORG_ROLE_TO_USER_ROLE.get(name)
    if role is None:
        logger.warning("Grafana returned an unsupported organization role %r", name)
        return UserRole.NONE
    return role


class _GrafanaUserRecord(TypedDict):
    """A Grafana ``/api/user`` or user-lookup record.

    ``email`` and ``isGrafanaAdmin`` are ``NotRequired`` because Grafana omits
    them for some users; the reader accesses both via ``.get()``.
    """

    id: int
    login: str
    email: NotRequired[str]
    isGrafanaAdmin: NotRequired[bool]


class _GrafanaOrgUserRecord(TypedDict):
    """A Grafana ``/api/org/users`` record.

    ``email`` and ``role`` are ``NotRequired`` because Grafana may omit them;
    the reader accesses both via ``.get()``.
    """

    userId: int
    login: str
    email: NotRequired[str]
    role: NotRequired[str]


def _find_org_user(
    records: list[_GrafanaOrgUserRecord], login_or_email: str
) -> _GrafanaOrgUserRecord | None:
    """Return the row a login or email names, ranking a login match first.

    Grafana allows a login shaped like an email, so one user's login can equal
    another's email; matching every login before any email keeps the result
    independent of listing order. Comparison is case-folded because Grafana
    treats logins case-insensitively, and a row whose field is absent or null is
    skipped rather than compared, so a blank input matches nothing.

    :param records: The org-users listing.
    :param login_or_email: The login or email to match, in any case.
    :return: The matching row, or ``None`` when the listing names neither.
    """
    wanted = login_or_email.casefold()
    for field in ("login", "email"):
        match = next(
            (
                row
                for row in records
                if (value := row.get(field)) and value.casefold() == wanted
            ),
            None,
        )
        if match is not None:
            return match
    return None


def _active_grafana_sdk() -> GrafanaSDK:
    """Return the live ``GrafanaSDK`` from the active auth provider.

    :return: The active provider, which is a ``GrafanaSDK`` while Grafana is the
        selected provider.
    """
    # lazy import: auth/config.py imports this module via the provider bundle, so
    # a module-level import here would cycle
    from app.core.auth.config import get_active_auth_provider

    return cast("GrafanaSDK", get_active_auth_provider())


class GrafanaTokenPayload(BaseTokenPayload):
    """Represent the payload of a Grafana token.

    Grafana issues no JWT that SEP introspects, so this model exists only to
    complete the provider bundle; it is never constructed at runtime.
    """

    @classmethod
    async def from_jwt(cls, token: str) -> NoReturn:  # noqa: ARG003
        """Reject decoding -- Grafana exposes no introspectable token payload.

        :param token: The token that would be decoded.
        :return: Never returns; the method always raises.
        :raises GrafanaException: Always -- unsupported for Grafana.
        """
        raise GrafanaException(detail="Grafana exposes no token payload to decode.")


class GrafanaUser(BaseUser):
    """Represent a Grafana user.

    The per-request credential is a SEP-signed identity assertion minted at
    login (:meth:`get_oauth_token`) and verified locally (:meth:`from_jwt`), so
    no Grafana call is needed to authenticate a request. Its ``id`` is a UUIDv5
    derived from Grafana's numeric user id -- widening the base ``UUID4`` field --
    so the identity stays stable across username changes.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: UUID

    @model_validator(mode="before")
    @classmethod
    def _decode_signed_token(cls, data: Any, info: ValidationInfo) -> Any:
        """Decode a signed identity assertion into user fields.

        A string input is a minted assertion: verify its signature, its expiry
        (the lifetime configured for the ``token_type`` the validation context
        expects, defaulting to the access lifetime), and that its ``typ`` claim
        matches that expected type. Any other input (a mapping from a Grafana
        record) is passed through untouched. Decode failures are raised as
        ``ValueError`` so Pydantic surfaces them as ``ValidationError`` -- the
        error type both auth deps and the SPA refresh route expect.

        The expiry is enforced before the ``typ`` claim is read, so a caller that
        accepts more than one type must validate one type per attempt; a single
        pass with the longest lifetime would check a short-lived assertion
        against a longer one's expiry.

        The assertion carries the identity's role as its own claim. A payload
        without it predates that claim and is refused rather than downgraded to
        a role derived from ``is_admin``, which would launder the degraded role
        into every assertion re-minted from it.

        :param data: The raw model input.
        :param info: The validation context carrying the expected ``token_type``.
        :return: The decoded claims mapping, or ``data`` unchanged.
        :raises ValueError: If the assertion is tampered, expired, malformed, of
            the wrong type, or carries no role claim.
        """
        if not isinstance(data, str):
            return data
        token_type = (info.context or {}).get("token_type", _TokenType.ACCESS)
        sdk = _active_grafana_sdk()
        max_age_by_type = {
            _TokenType.ACCESS: sdk.access_token_max_age,
            _TokenType.REFRESH: sdk.refresh_token_max_age,
            _TokenType.EXCHANGE: sdk.exchange_token_max_age,
        }
        max_age = max_age_by_type.get(
            token_type, sdk.access_token_max_age
        ).total_seconds()
        try:
            payload = _TOKEN_SERIALIZER.loads(data, max_age=max_age)
        except BadData as exc:
            raise ValueError("invalid or expired Grafana session token") from exc
        if payload.get("typ") != token_type:
            raise ValueError("unexpected Grafana token type")
        if "role" not in payload:
            raise ValueError("Grafana session token carries no role claim")
        return payload

    @staticmethod
    def _mint(user: "GrafanaUser", token_type: _TokenType) -> str:
        """Mint a signed identity assertion of ``token_type`` for ``user``.

        :param user: The user whose identity the assertion carries.
        :param token_type: The assertion type recorded as the ``typ`` claim
            (wire values: ``"access"``, ``"refresh"``, ``"exchange"``).
        :return: The signed, URL-safe identity assertion.
        """
        payload = user.model_dump(
            mode="json", include={"id", "username", "email", "role", "is_admin"}
        )
        payload["typ"] = token_type
        return _TOKEN_SERIALIZER.dumps(payload)

    @staticmethod
    def _oauth_token_for(user: "GrafanaUser", grafana: GrafanaSDK) -> OAuthToken:
        """Build an OAuth token pair (access + refresh) for ``user``.

        :param user: The authenticated user.
        :param grafana: The active SDK, read for the access-token lifetime.
        :return: An OAuth token whose ``access_token`` / ``refresh_token`` are
            SEP-signed assertions.
        """
        empty = ""
        bearer = "Bearer"
        return OAuthToken(
            access_token=GrafanaUser._mint(user, _TokenType.ACCESS),
            refresh_token=GrafanaUser._mint(user, _TokenType.REFRESH),
            id_token=empty,
            token_type=bearer,
            expires_in=grafana.access_token_max_age,
            scope=empty,
        )

    @classmethod
    def _from_grafana_record(
        cls, record: _GrafanaUserRecord, orgs: Iterable[Mapping[str, Any]]
    ) -> Self:
        """Build a user from a Grafana ``/api/user`` or user-lookup record.

        Grafana's numeric ``id`` is the stable subject: the SEP UUID is derived
        from it so a username change does not change the identity.

        The server-admin flag outranks every org membership; without it the
        user holds the highest role any of their orgs grants. Roles rank through
        :func:`_rank_org_role`, so a membership carrying no role ranks lowest
        silently and one naming a role Grafana does not define ranks lowest and
        is logged -- an unreadable membership grants no more than it proves.

        :param record: A Grafana record carrying ``id``, ``login``, ``email``,
            and ``isGrafanaAdmin``.
        :param orgs: The memberships to rank, flattened to their highest role.
            They may be every org the user belongs to or only the ones a single
            org's listing proves.
        :return: The mapped ``GrafanaUser``.
        """
        if record.get("isGrafanaAdmin"):
            role = UserRole.SUPER_ADMIN
        else:
            role = max(
                (_rank_org_role(org.get("role")) for org in orgs),
                default=UserRole.NONE,
            )
        return cls(
            id=uuid5(NAMESPACE_URL, f"grafana:{record['id']}"),
            username=record["login"],
            email=record.get("email") or "",
            role=role,
        )

    @classmethod
    def _from_org_user_record(cls, record: _GrafanaOrgUserRecord) -> Self:
        """Build a user from a Grafana ``/api/org/users`` record.

        The org-users listing carries ``userId`` and a single ``role`` per row,
        unlike the ``/api/user`` shape handled by :meth:`_from_grafana_record`.
        Roles rank through :func:`_rank_org_role`, so a row this provider
        cannot rank grants nothing and is logged rather than defaulting upwards.

        :param record: A Grafana org-user record carrying ``userId``, ``login``,
            ``email``, and ``role``.
        :return: The mapped ``GrafanaUser``.
        """
        return cls(
            id=uuid5(NAMESPACE_URL, f"grafana:{record['userId']}"),
            username=record["login"],
            email=record.get("email") or "",
            role=_rank_org_role(record.get("role")),
        )

    @staticmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        """Mint an access + refresh assertion pair for the password or refresh grant.

        The password grant authenticates against Grafana once and mints the pair;
        the refresh grant verifies a prior refresh assertion locally and re-mints a
        rotated pair with no Grafana call. Both ``access_token`` and
        ``refresh_token`` are SEP-signed assertions rather than Grafana credentials
        (Grafana issues no OAuth tokens).

        :param code: Unsupported -- Grafana has no authorization-code grant.
        :param username: The Grafana username (password grant).
        :param password: The Grafana password (password grant).
        :param refresh_token: A prior SEP-signed refresh assertion (refresh grant).
        :return: An OAuth token whose ``access_token`` / ``refresh_token`` are the
            minted assertions.
        :raises GrafanaException: For the authorization-code grant or missing
            password-grant credentials.
        :raises ValidationError: When the refresh assertion is invalid, expired, or
            not a refresh token.
        """
        if code is not None:
            raise GrafanaException(detail="Grafana has no authorization-code grant.")
        grafana = _active_grafana_sdk()
        if refresh_token is not None:
            user = GrafanaUser.model_validate(
                refresh_token, context={"token_type": _TokenType.REFRESH}
            )
            return GrafanaUser._oauth_token_for(user, grafana)
        if not (username and password):
            raise GrafanaException(detail="Grafana requires a username and password.")
        session = await grafana.login(username, password)
        record = cast("_GrafanaUserRecord", await grafana.get_current_user(session))
        orgs = await grafana.get_current_user_orgs(session)
        user = GrafanaUser._from_grafana_record(record, orgs)
        return GrafanaUser._oauth_token_for(user, grafana)

    @staticmethod
    async def _user_from_ambient_session(session: str) -> "GrafanaUser | None":
        """Read the identity behind an ambient Grafana session cookie.

        ``GrafanaException`` is itself an ``HTTPException``, so the non-401
        branch must re-raise: collapsing every upstream failure into ``None``
        would report a Grafana outage as "no session". Grafana's 401 arrives as a
        bare ``HTTPException`` rather than a typed subclass, so the status is
        inspected rather than caught by class.

        :param session: The ambient Grafana session cookie value off the request.
        :return: The identity behind the session, or ``None`` when Grafana
            rejects it (HTTP 401).
        :raises HTTPException: For a non-401 upstream error (5xx or other),
            including the ``GrafanaException`` raised when Grafana is unreachable.
        """
        grafana = _active_grafana_sdk()
        try:
            record = cast("_GrafanaUserRecord", await grafana.get_current_user(session))
            orgs = await grafana.get_current_user_orgs(session)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                return None
            raise
        return GrafanaUser._from_grafana_record(record, orgs)

    @staticmethod
    async def oauth_token_from_session(session: str) -> OAuthToken | None:
        """Mint an access + refresh assertion pair from an ambient Grafana session.

        Validate the ambient session cookie value against Grafana and mint a SEP
        token pair, mirroring the password grant without a fresh ``login()`` --
        the caller already holds the cookie off the incoming request.

        :param session: The ambient Grafana session cookie value off the request.
        :return: A minted ``OAuthToken`` on a valid session, or ``None`` when
            Grafana rejects the session (HTTP 401) so the caller falls back to the
            login form.
        :raises HTTPException: For a non-401 upstream error (5xx or other),
            including the ``GrafanaException`` raised when Grafana is unreachable.
        """
        user = await GrafanaUser._user_from_ambient_session(session)
        if user is None:
            return None
        return GrafanaUser._oauth_token_for(user, _active_grafana_sdk())

    @staticmethod
    async def exchange_token_from_session(
        session: str,
    ) -> SessionExchangeTokenResponse | None:
        """Mint a short-lived exchange assertion from an ambient Grafana session.

        Unlike :meth:`oauth_token_from_session`, mint a single assertion and no
        refresh credential: the holder renews by exchanging the ambient session
        again, so losing that session ends embedded access within one assertion
        lifetime. The payload carries the same identity claims the other grants
        mint -- no Grafana session material and no service-account credential.

        :param session: The ambient Grafana session cookie value off the request.
        :return: The minted bearer and its lifetime on a valid session, or
            ``None`` when Grafana rejects the session (HTTP 401).
        :raises HTTPException: For a non-401 upstream error (5xx or other),
            including the ``GrafanaException`` raised when Grafana is unreachable.
        """
        user = await GrafanaUser._user_from_ambient_session(session)
        if user is None:
            return None
        return SessionExchangeTokenResponse(
            access_token=GrafanaUser._mint(user, _TokenType.EXCHANGE),
            expires_in=_active_grafana_sdk().exchange_token_max_age,
        )

    @staticmethod
    async def invalidate_oauth_token(access_token: str) -> None:  # noqa: ARG004
        """Skip invalidation: Grafana holds no SEP-minted assertion to revoke.

        :param access_token: The access token that would be invalidated.
        """
        return

    @staticmethod
    async def invalidate_tokens_for_user(
        username: str,  # noqa: ARG004
        exclude_tokens: Sequence[str] = (),  # noqa: ARG004
    ) -> None:
        """Skip revocation: SEP mints stateless assertions with nothing to revoke.

        :param username: The username whose tokens would be invalidated.
        :param exclude_tokens: Access tokens that would be excluded.
        """
        return

    @classmethod
    async def get_user(cls, username: NonEmptyStr) -> Self:
        """Fetch a single user by login or email.

        The user-lookup endpoint needs Grafana's instance-scoped ``users:read``,
        which only a Server Admin holds, so a service account scoped to a single
        org is refused. That refusal alone falls back to the org-users listing the
        same token already reads for :meth:`get_users`. Every other status
        propagates: a 401 means the credential itself is bad and a 404 means the
        user is genuinely absent, and re-reading a listing answers neither.
        Nothing in this provider raises a SEP-side 403, so the status is
        unambiguous here.

        The lookup endpoint carries the server-admin flag but no org memberships,
        so the target's membership is read from the org-users listing -- the same
        source :meth:`get_users` reads, so an org role reported there is reported
        here too. A server admin still outranks that listing, which carries no
        server-admin flag of its own, so its rows go unread. The listing is scoped
        to the service account's own org, so a target whose only membership is in
        another org is absent from it and ranks lowest.

        The numeric id keys the match on this path: it is the identifier both
        shapes agree on, while a login can differ in case or be given as an email.
        The fallback has no lookup record to key on, so it matches on the login or
        email instead, and reports the org role with no server-admin flag to
        outrank it -- the same limitation :meth:`get_users` carries. Both paths
        read the listing through :meth:`_org_user_records`, so they inherit its
        cache, which can answer both stale and after the lookup has begun refusing.

        :param username: The login or email to look up.
        :return: The mapped ``GrafanaUser``.
        :raises HTTPException: Whatever the lookup endpoint raised, for every
            status other than 403, or whatever the org-users listing raised, on
            either path -- so a role is never reported from membership data that
            could not be read.
        :raises HTTPNotFoundException: If the org-scoped fallback holds no such
            user.
        :raises GrafanaException: If the org-users listing breaks the record
            contract.
        """
        try:
            record = cast(
                "_GrafanaUserRecord", await _active_grafana_sdk().lookup_user(username)
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_403_FORBIDDEN:
                raise
            return await cls._get_user_from_org_listing(username)
        if record.get("isGrafanaAdmin"):
            return cls._from_grafana_record(record, [])
        orgs = [
            row
            for row in await cls._org_user_records()
            if row["userId"] == record["id"]
        ]
        return cls._from_grafana_record(record, orgs)

    @classmethod
    async def _org_user_records(cls) -> list[_GrafanaOrgUserRecord]:
        """Read the org-users listing, refusing a payload off contract.

        The listing is validated before anything reads a field, so a shape
        Grafana never promised surfaces as an upstream failure instead of
        escaping from inside the mapping as an unhandled key or attribute error.

        Every field either mapper reads is checked, not only the ones the match
        compares: a row without ``userId`` or with an unhashable ``role`` passes
        a narrower gate and then crashes inside the mapping instead.

        A null ``email`` or ``role`` passes: the mappers already read those
        fields as optional, so refusing them would reject a listing the provider
        has always been able to map.

        :return: The listing rows.
        :raises HTTPException: Whatever the org-users listing raised.
        :raises GrafanaException: If the payload is not a list of records each
            carrying an integer ``userId`` and a string ``login``, with
            ``email`` and ``role`` either a string or absent.
        """
        payload = await _active_grafana_sdk().get_org_users()
        if not isinstance(payload, list) or not all(
            isinstance(row, Mapping)
            and isinstance(row.get("userId"), int)
            and isinstance(row.get("login"), str)
            and isinstance(row.get("email"), str | None)
            and isinstance(row.get("role"), str | None)
            for row in payload
        ):
            raise GrafanaException(detail="Grafana returned an unreadable user list.")
        return cast("list[_GrafanaOrgUserRecord]", payload)

    @classmethod
    async def _get_user_from_org_listing(cls, username: NonEmptyStr) -> Self:
        """Resolve a user from the listing an org-scoped service account can read.

        The listing accepts either field the lookup endpoint's ``loginOrEmail``
        accepts, matched by :func:`_find_org_user`. A matched row ranks through
        the same policy :meth:`get_users` applies, so holding no org role reports
        the lowest role rather than failing: that is a state Grafana models, and
        the two read paths must not disagree about one row.

        :param username: The login or email to resolve.
        :return: The mapped ``GrafanaUser``.
        :raises HTTPException: Whatever the org-users listing raised.
        :raises HTTPNotFoundException: If no org user matches ``username``.
        :raises GrafanaException: If the listing breaks the record contract.
        """
        record = _find_org_user(await cls._org_user_records(), username)
        if record is None:
            raise HTTPNotFoundException(detail="User not found")
        return cls._from_org_user_record(record)

    @classmethod
    async def get_users(cls) -> list[Self]:
        """List the org users.

        Org-user records carry a single org role and no server-admin flag, so
        the role reflects that org membership only and never reaches
        ``SUPER_ADMIN``.

        :return: The mapped ``GrafanaUser`` instances.
        :raises HTTPException: Whatever the org-users listing raised.
        :raises GrafanaException: If the listing breaks the record contract.
        """
        return [
            cls._from_org_user_record(record)
            for record in await cls._org_user_records()
        ]

    @classmethod
    async def from_token_payload(cls, token_payload: BaseTokenPayload) -> NoReturn:  # noqa: ARG003
        """Reject -- Grafana exposes no token payload to build a user from.

        :param token_payload: The payload that would be used.
        :return: Never returns; the method always raises.
        :raises GrafanaException: Always -- unsupported for Grafana.
        """
        raise GrafanaException(detail="Grafana exposes no token payload.")

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Build a user by verifying a minted access assertion.

        :param token: The signed access assertion (the per-request Bearer
            credential).
        :return: The verified ``GrafanaUser``.
        :raises ValidationError: If the assertion is tampered, expired, malformed,
            or not an access token.
        """
        user = cls.model_validate(token, context={"token_type": _TokenType.ACCESS})
        user.access_token = token
        return user

    @classmethod
    async def from_bearer(cls, token: str) -> Self:
        """Build a user by verifying an assertion presented as a Bearer credential.

        Try each accepted type in turn so every candidate is checked against its
        own lifetime -- the expiry is enforced before the ``typ`` claim is read,
        so one pass with a widened lifetime would grant a short-lived exchange
        assertion the full access-token lifetime. A refresh assertion matches no
        accepted type and is refused.

        :param token: The signed assertion carried in the ``Authorization:
            Bearer`` header.
        :return: The verified ``GrafanaUser``.
        :raises ValidationError: If the assertion is tampered, malformed, expired
            against the lifetime of every accepted type, or of a type this
            surface does not accept.
        """
        last_error: ValidationError | None = None
        for token_type in _BEARER_TOKEN_TYPES:
            try:
                user = cls.model_validate(token, context={"token_type": token_type})
            except ValidationError as exc:
                last_error = exc
                continue
            user.access_token = token
            return user
        if last_error is None:
            raise GrafanaException("No bearer token type is accepted on this surface.")
        raise last_error

    @classmethod
    async def from_code(cls, code: str) -> NoReturn:  # noqa: ARG003
        """Reject -- Grafana has no authorization-code grant.

        :param code: The authorization code that would be exchanged.
        :return: Never returns; the method always raises.
        :raises GrafanaException: Always -- unsupported for Grafana.
        """
        raise GrafanaException(detail="Grafana has no authorization-code grant.")

    @classmethod
    async def from_password(cls, username: str, password: str) -> Self:
        """Build a user by authenticating a username and password.

        :param username: The Grafana username.
        :param password: The Grafana password.
        :return: The authenticated ``GrafanaUser``.
        """
        oauth_token = await cls.get_oauth_token(username=username, password=password)
        return await cls.from_jwt(oauth_token.access_token)
