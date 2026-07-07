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

from collections.abc import Sequence
from typing import Any, cast, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import model_validator

from app.core.auth.models import BaseTokenPayload, BaseUser, OAuthToken
from app.core.auth.providers.grafana.sdk import GrafanaException, GrafanaSDK
from app.core.config import settings
from app.core.utils.fields import NonEmptyStr

_TOKEN_SERIALIZER = URLSafeTimedSerializer(
    settings.SECRET_KEY.get_secret_value(), salt="sep.auth.grafana.v1"
)
_ID_NAMESPACE = uuid5(NAMESPACE_URL, "https://percona.com/sep/auth/grafana")


def _active_grafana_sdk() -> GrafanaSDK:
    """Return the live ``GrafanaSDK`` from the active auth provider.

    :return: The active provider, which is a ``GrafanaSDK`` while Grafana is the
        selected provider.
    """
    # lazy import: auth/config.py imports this module via the provider bundle, so
    # a module-level import here would cycle
    from app.core.auth.config import get_active_auth_provider

    return cast(GrafanaSDK, get_active_auth_provider())


class GrafanaTokenPayload(BaseTokenPayload):
    """Represent the payload of a Grafana token.

    Grafana issues no JWT that SEP introspects, so this model exists only to
    complete the provider bundle; it is never constructed at runtime.
    """

    @classmethod
    async def from_jwt(cls, token: str) -> Self:  # noqa: ARG003
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

    id: UUID

    @model_validator(mode="before")
    @classmethod
    def _decode_signed_token(cls, data: Any) -> Any:
        """Decode a signed identity assertion into user fields.

        A string input is a minted assertion: verify its signature and expiry
        and return the embedded claims. Any other input (a mapping from a
        Grafana record) is passed through untouched. Decode failures are raised
        as ``ValueError`` so Pydantic surfaces them as ``ValidationError`` -- the
        error type both auth deps expect.

        :param data: The raw model input.
        :return: The decoded claims mapping, or ``data`` unchanged.
        :raises ValueError: If the assertion is tampered, expired, or malformed.
        """
        if isinstance(data, str):
            try:
                return _TOKEN_SERIALIZER.loads(
                    data, max_age=_active_grafana_sdk().token_max_age.total_seconds()
                )
            except BadData as exc:
                raise ValueError("invalid or expired Grafana session token") from exc
        return data

    def _mint(self) -> str:
        """Mint a signed identity assertion carrying this user's identity.

        :return: The signed, URL-safe identity assertion.
        """
        return _TOKEN_SERIALIZER.dumps(
            self.model_dump(
                mode="json", include={"id", "username", "email", "is_admin"}
            )
        )

    @classmethod
    def _from_grafana_record(
        cls, record: dict[str, Any], orgs: list[dict[str, Any]]
    ) -> Self:
        """Build a user from a Grafana ``/api/user`` or user-lookup record.

        Grafana's numeric ``id`` is the stable subject: the SEP UUID is derived
        from it so a username change does not change the identity.

        :param record: A Grafana record carrying ``id``, ``login``, ``email``,
            and ``isGrafanaAdmin``.
        :param orgs: The user's org memberships; an ``Admin`` role in any org
            grants admin, as does the server-admin flag.
        :return: The mapped ``GrafanaUser``.
        """
        is_admin = bool(record.get("isGrafanaAdmin")) or any(
            org.get("role") == "Admin" for org in orgs
        )
        return cls(
            id=uuid5(_ID_NAMESPACE, f"grafana:{record['id']}"),
            username=record["login"],
            email=record.get("email") or "",
            is_admin=is_admin,
        )

    @classmethod
    def _from_org_user_record(cls, record: dict[str, Any]) -> Self:
        """Build a user from a Grafana ``/api/org/users`` record.

        The org-users listing carries ``userId`` and a single ``role`` per row,
        unlike the ``/api/user`` shape handled by :meth:`_from_grafana_record`.

        :param record: A Grafana org-user record carrying ``userId``, ``login``,
            ``email``, and ``role``.
        :return: The mapped ``GrafanaUser``.
        """
        return cls(
            id=uuid5(_ID_NAMESPACE, f"grafana:{record['userId']}"),
            username=record["login"],
            email=record.get("email") or "",
            is_admin=record.get("role") == "Admin",
        )

    @staticmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        """Authenticate against Grafana and mint an identity assertion.

        Only the resource-owner password grant is supported: Grafana issues no
        authorization code and no refresh token, so the ``access_token`` returned
        is a SEP-signed identity assertion rather than a Grafana credential.

        :param code: Unsupported -- Grafana has no authorization-code grant.
        :param username: The Grafana username.
        :param password: The Grafana password.
        :param refresh_token: Unsupported -- Grafana issues no refresh token.
        :return: An OAuth token whose ``access_token`` is the minted assertion.
        :raises GrafanaException: For any grant other than username/password.
        """
        if code is not None or refresh_token is not None:
            raise GrafanaException(detail="Grafana supports only the password grant.")
        if not (username and password):
            raise GrafanaException(detail="Grafana requires a username and password.")
        grafana = _active_grafana_sdk()
        session = await grafana.login(username, password)
        record = await grafana.get_current_user(session)
        orgs = await grafana.get_current_user_orgs(session)
        user = GrafanaUser._from_grafana_record(record, orgs)
        empty = ""
        bearer = "Bearer"
        return OAuthToken(
            access_token=GrafanaUser._mint(user),
            token_type=bearer,
            expires_in=grafana.token_max_age,
            refresh_token=empty,
            id_token=empty,
            scope=empty,
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

        The user-lookup endpoint carries the server-admin flag but no org
        memberships, so ``is_admin`` here reflects only the Grafana server-admin
        role -- unlike the login flow, which also grants admin for an org-admin
        role.

        :param username: The login or email to look up.
        :return: The mapped ``GrafanaUser``.
        """
        record = await _active_grafana_sdk().lookup_user(username)
        return cls._from_grafana_record(record, [])

    @classmethod
    async def get_users(cls) -> list[Self]:
        """List the org users.

        Org-user records carry a single org role and no server-admin flag, so
        ``is_admin`` reflects the org-admin role only.

        :return: The mapped ``GrafanaUser`` instances.
        """
        records = await _active_grafana_sdk().get_org_users()
        return [cls._from_org_user_record(record) for record in records]

    @classmethod
    async def from_token_payload(cls, token_payload: BaseTokenPayload) -> Self:  # noqa: ARG003
        """Reject -- Grafana exposes no token payload to build a user from.

        :param token_payload: The payload that would be used.
        :return: Never returns; the method always raises.
        :raises GrafanaException: Always -- unsupported for Grafana.
        """
        raise GrafanaException(detail="Grafana exposes no token payload.")

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Build a user by verifying a minted identity assertion.

        :param token: The signed identity assertion.
        :return: The verified ``GrafanaUser``.
        :raises ValidationError: If the assertion is tampered, expired, or
            malformed.
        """
        user = cls.model_validate(token)
        user.access_token = token
        return user

    @classmethod
    async def from_code(cls, code: str) -> Self:  # noqa: ARG003
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
