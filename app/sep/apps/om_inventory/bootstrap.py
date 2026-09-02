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

"""Dispatch the bootstrap payload to one host -- PoC, single host, replica set only.

Deliberately not shaped like :mod:`app.sep.apps.om_inventory.dispatch`, which fans
out to every executor host and waits for each to finish (tens of seconds to a couple
of minutes for a full sweep). This dispatches to exactly **one** host and returns as
soon as the Nomad job is queued -- a single HTTP round trip, not a wait for
completion -- so calling it from a request handler does not violate the "the caller
must never wait for a Nomad job" rule ``api_routes.py``'s module docstring states:
that rule is about waiting for a job to *finish*, and this never does. Progress after
that point is read from the Tasks API's own, already-generic
``GET /history/{id}`` and ``GET /history/{id}/logs/`` -- nothing here polls or stores
a second copy of that state.

No new table, no new Celery task: this PoC's whole purpose is to prove the execution
path works before PMM-15347's still-open questions (project/cluster shape, secrets
storage, partial-failure policy -- see ``PMM-15347/questions.md``) are answered and
shape what a real run-tracking model should look like. Building one now would very
likely need rebuilding once those land.
"""

import base64
import json
import logging
import secrets
from pathlib import Path

from app.core.requests import RemoteAPI
from app.sep.apps.om_inventory import payload as payload_pkg
from app.sep.apps.om_inventory.models import BootstrapRequest, OmHost

logger = logging.getLogger(__name__)

#: Reuses the same pre-seeded system task the probe rides -- see dispatch.py's
#: module docstring for why: ``POST /execute/run-python`` with a ``file://`` payload
#: is the generic "run this script on this host" primitive, not something specific
#: to reading facts.
RUN_PYTHON_TASK = "run-python"
REQUIREMENTS = "pymongo>=4.6,<5"
JOB_ID_PREFIX = "om-bootstrap"
BOOTSTRAP_PAYLOAD_PATH = Path(payload_pkg.__file__).parent / "bootstrap.py"

#: Matches psmdb/scripts/bootstrap.sh's keyFile size -- comfortably inside MongoDB's
#: 6-1024 base64-character requirement for a keyFile.
KEY_FILE_BYTES = 756


def generate_keyfile_b64(num_bytes: int) -> str:
    """Return ``num_bytes`` of cryptographically random binary data, base64-encoded.

    Binary, not text: the payload writes the decoded bytes straight to the keyFile
    path. Not password-shaped and not meant to round-trip through
    ``.decode("utf-8")`` -- that is what :func:`generate_password_b64` is for.

    :param num_bytes: How many random bytes to generate.
    :return: The base64-encoded secret, safe to embed in a JSON config.
    """
    return base64.b64encode(secrets.token_bytes(num_bytes)).decode("ascii")


def generate_password_b64(length: int = 24) -> str:
    """Return a random URL-safe password, base64-encoded for JSON transport.

    Unlike :func:`generate_keyfile_b64`, the underlying secret is text (from
    :func:`secrets.token_urlsafe`) *before* it is base64-encoded -- so decoding it
    back with ``.decode("utf-8")``, which :func:`dispatch_bootstrap` does to hand the
    admin password back to the caller, is well-defined. Encoded anyway, for the same
    reason the keyFile is: consistency with "every ``*_b64`` field in this config is
    base64" rather than a special case a reader has to remember.

    :param length: The password's length in characters, before encoding.
    :return: The base64-encoded password.
    """
    return base64.b64encode(secrets.token_urlsafe(length).encode("utf-8")).decode("ascii")


def build_bootstrap_config(host: OmHost, request: BootstrapRequest) -> tuple[str, str, str]:
    """Build the payload config for one host's bootstrap, and its generated secrets.

    Secrets are generated **here**, per dispatch, and never persisted by this
    dispatcher -- they exist only in the config handed to this one Nomad job and in
    the response returned to the caller once. Where they should actually live is
    ``PMM-15347/questions.md`` Q7, unresolved; this is the PoC's placeholder, not the
    answer.

    :param host: The host row to bootstrap.
    :param request: The requested configuration.
    :return: ``(config_json, key_file_b64, admin_password_b64)`` -- the config to send
        to Nomad, and the two generated secrets, returned separately so the caller can
        surface the admin password once without parsing it back out of the config.
    """
    key_file_b64 = generate_keyfile_b64(KEY_FILE_BYTES)
    admin_password_b64 = generate_password_b64()
    # Same preference as dispatch.py's build_config: the node name over the address,
    # for the sidecar case where pmm-agent's own container address has nothing
    # listening on the database port.
    member_host = host.name or host.address
    config = {
        "replica_set_name": request.replica_set_name,
        "mongodb_version": request.mongodb_version,
        "data_path": request.data_path,
        "log_path": request.log_path,
        "port": request.port,
        "bind_ip": request.bind_ip,
        "member_host": member_host,
        "key_file_path": request.key_file_path,
        "key_file_b64": key_file_b64,
        "admin_username": request.admin_username,
        "admin_password_b64": admin_password_b64,
    }
    return (
        json.dumps(config, separators=(",", ":"), sort_keys=True),
        key_file_b64,
        admin_password_b64,
    )


async def dispatch_bootstrap(
    tasks_api: RemoteAPI, host: OmHost, request: BootstrapRequest
) -> tuple[int, str]:
    """Queue the bootstrap payload against one host and return its task history id.

    Does **not** wait for the run to finish -- see the module docstring. A caller
    polls ``GET /api/tasks/history/{id}`` and
    ``GET /api/tasks/history/{id}/logs/`` directly for progress, the same generic
    endpoints ``om tasks show`` already uses.

    :param tasks_api: The tasks API client.
    :param host: The host to bootstrap. Must carry an ``executor_host``, the caller's
        responsibility to check -- this dispatches unconditionally.
    :param request: The requested configuration.
    :return: The dispatched run's task history id, and the generated admin password
        (base64-decoded, plain text) -- returned once, here, because nothing else
        will hold it after this call returns.
    :raises RuntimeError: When the Tasks API accepts the dispatch but returns no
        history id.
    """
    config, _key_file_b64, admin_password_b64 = build_bootstrap_config(host, request)
    created = await tasks_api.post(
        f"/execute/{RUN_PYTHON_TASK}",
        json={
            "meta": {
                "target": host.executor_host,
                "config": config,
                "requirements": REQUIREMENTS,
                "_job_id_prefix": JOB_ID_PREFIX,
            },
            "payload": f"file://{BOOTSTRAP_PAYLOAD_PATH}",
            "anonymize_mask": 0,
        },
    )
    if not isinstance(created, dict) or "id" not in created:
        raise RuntimeError("Tasks API did not return a task history id")
    task_history_id = int(created["id"])
    logger.info(
        "OM inventory: dispatched bootstrap to %s (node %s), history %s",
        host.executor_host,
        host.node_id,
        task_history_id,
    )
    return task_history_id, base64.b64decode(admin_password_b64).decode("utf-8")
