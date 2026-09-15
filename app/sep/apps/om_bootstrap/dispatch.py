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

"""Dispatch one bootstrap step's action to a host, as root, via Nomad.

Rides the pre-seeded system ``exec-artifact`` task rather than ``run-python``
(``om_inventory``'s own choice, ``om_inventory/dispatch.py``): ``run-python``'s
job template has no ``sudo`` branch at all, so a step needing root (installing a
package, writing ``/etc/mongod.conf``, managing a systemd unit -- everything
:class:`~app.sep.apps.om_bootstrap.strategies.packages.PackagesInstallStrategy`
does) would only work by accident, if the Nomad client agent itself happens to
run as root. ``exec-artifact`` has an explicit sudo path: its job template keys
off the ``interpreter`` meta literally starting with ``"sudo "``
(``app/tasks/db/seed.py``) and runs ``sudo <interpreter> local/script``.

``exec-artifact`` downloads its script as a Nomad artifact rather than a
dispatch payload (unlike ``run-python``), which means the script has to exist as
a real file at a real URL *before* dispatch. Every existing consumer
(``dipper``, ``snippets``) serves a fixed, developer-authored file for this --
none of them write one on the fly, because none of them need to: their script
content never changes. A bootstrap step's command is different per run, host,
and step, so this module is the first to actually generate the file it serves,
which is the reason it needs a scratch directory (:func:`step_scripts_dir`) at
all -- see PMM-15347/plan.md item 9's note on this.

Deliberately not modeled as a :class:`~app.sep.snippets.models.snippet.BaseSnippet`:
that abstraction exists for catalogued, user-parameterized scripts with a
validated execution model, and a bootstrap step is neither -- its content is
fixed once :class:`~app.sep.apps.om_bootstrap.strategy.StepAction` is built, with
nothing left for a user to supply. Reusing
:class:`~app.sep.snippets.models.snippet.SnippetExecutionMeta` directly (the data
envelope ``exec-artifact`` actually reads) gets the same wire format without the
unneeded layer above it.

Dispatch here is fire-and-forget, matching the shape
``om_inventory/bootstrap.py``'s own PoC proved works for this kind of long-running
work: this returns as soon as the Tasks API accepts the dispatch, carrying no
opinion about whether the step has started, let alone finished. Polling
``TaskHistory`` to completion and writing the result back onto
:class:`~app.sep.apps.om_bootstrap.strategy.StepRecord` is the reconciliation
task's job, not this module's -- not yet built.
"""

import hashlib
import shlex
from pathlib import Path
from tempfile import gettempdir

from fastapi import Request

from app.core.requests import RemoteAPI
from app.sep.apps.framework.script_helpers import (
    build_artifact_download_url,
    post_task_execution,
)
from app.sep.apps.om_bootstrap.strategy import StepAction
from app.sep.snippets.models.snippet import SnippetExecutionMeta

__all__ = [
    "ARTIFACT_TYPE",
    "EXEC_ARTIFACT_TASK",
    "ROOT_INTERPRETER",
    "cleanup_step_script",
    "dispatch_step",
    "step_scripts_dir",
]

#: The pre-seeded system task that runs an artifact-downloaded script as root.
EXEC_ARTIFACT_TASK = "exec-artifact"
#: ``exec-artifact``'s job template keys its sudo branch on the interpreter meta
#: literally starting with ``"sudo "`` (``app/tasks/db/seed.py``) -- nothing else
#: triggers it.
ROOT_INTERPRETER = "sudo bash"
#: The ``artifact_base_dirs`` discriminator ``om_bootstrap`` registers
#: :func:`step_scripts_dir` under -- see ``app.py``.
ARTIFACT_TYPE = "om_bootstrap_step"


def step_scripts_dir() -> Path:
    """Return the scratch directory step scripts are written to, creating it if needed.

    A fixed path under the system temp directory, not a per-call
    :func:`tempfile.mkdtemp`: :func:`~app.sep.apps.framework.base.BaseApp`
    declares this directory once, at import time, as the thunk
    ``artifact_base_dirs`` calls on every download -- it has to resolve to the
    same directory every time, not a fresh one per call.

    :return: The scratch directory, created if it did not already exist.
    """
    directory = Path(gettempdir()) / "sep-om-bootstrap-steps"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def step_script_filename(run_id: str, host: str, step_name: str) -> str:
    """Name the script file for one run/host/step triple.

    Deterministic and reused on retry: a failed step retried under Adamo's
    decided policy (PMM-15347/questions.md Q8) dispatches again under the exact
    same name, so a retry simply overwrites the previous attempt's script rather
    than accumulating one file per attempt.

    :param run_id: The bootstrap run this step belongs to.
    :param host: The node name being bootstrapped.
    :param step_name: The step's name, from
        :meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.plan_steps`.
    :return: The script's filename, unique within :func:`step_scripts_dir`.
    """
    return f"{run_id}_{host}_{step_name}.sh"


def build_step_script(action: StepAction) -> str:
    """Render a step's action as a standalone POSIX shell script.

    ``shlex.join`` rather than assuming ``action.command`` is already a shell
    string: some builders return an ``["sh", "-c", "..."]`` triple (a command
    that itself needs a shell), others a plain argv like
    ``["systemctl", "enable", "--now", "mongod"]`` -- joining either shape with
    proper quoting into one line means this function does not need to know or
    care which shape a given strategy produced.

    :param action: The step's action.
    :return: The script's full text, including the shebang.
    """
    return f"#!/bin/sh\nset -eu\n{shlex.join(action.command)}\n"


def write_step_script(
    run_id: str, host: str, step_name: str, action: StepAction
) -> tuple[Path, str]:
    """Write a step's script into the scratch directory.

    :param run_id: The bootstrap run this step belongs to.
    :param host: The node name being bootstrapped.
    :param step_name: The step's name.
    :param action: The step's action.
    :return: The written file's path, and its MD5 digest --
        :class:`~app.sep.snippets.models.snippet.SnippetExecutionMeta` requires
        the digest to verify the download on the executor side.
    """
    content = build_step_script(action)
    path = step_scripts_dir() / step_script_filename(run_id, host, step_name)
    path.write_text(content)
    digest = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
    return path, digest


def cleanup_step_script(run_id: str, host: str, step_name: str) -> None:
    """Remove a step's script once its dispatch has reached a terminal status.

    Best-effort by design, matching
    :func:`~app.sep.apps.om_inventory.dispatch._release`'s own reasoning: a
    script that fails to delete is a few stray bytes in a scratch directory, not
    a run that needs to fail because its cleanup did.

    :param run_id: The bootstrap run this step belongs to.
    :param host: The node name being bootstrapped.
    :param step_name: The step's name.
    """
    path = step_scripts_dir() / step_script_filename(run_id, host, step_name)
    path.unlink(missing_ok=True)


async def dispatch_step(
    tasks_api: RemoteAPI,
    request: Request | None,
    run_id: str,
    host: str,
    step_name: str,
    action: StepAction,
) -> int:
    """Dispatch one step's action to ``host``, as root, and return its task history id.

    Does **not** wait for the run to finish -- see the module docstring. A caller
    polls ``GET /api/tasks/history/{id}`` for progress, the same generic endpoint
    ``om_inventory/bootstrap.py``'s PoC already established this pattern with.

    :param tasks_api: The Tasks API client.
    :param request: The current request, whose host builds the artifact download
        URL -- ``None`` falls back to the configured base URL, for callers
        outside a request context (e.g. a Celery reconciliation task retrying a
        step).
    :param run_id: The bootstrap run this step belongs to.
    :param host: The node name being bootstrapped.
    :param step_name: The step's name.
    :param action: The step's action.
    :return: The dispatched run's task history id.
    :raises RuntimeError: When the Tasks API accepts the dispatch but returns no
        history id.
    """
    filename = step_script_filename(run_id, host, step_name)
    _, digest = write_step_script(run_id, host, step_name, action)
    snippet_source = build_artifact_download_url(
        request, artifact_type=ARTIFACT_TYPE, filename=filename, md5_digest=digest
    )
    meta = SnippetExecutionMeta(
        target=host,
        interpreter=ROOT_INTERPRETER,
        snippet_source=snippet_source,
        snippet_filename=filename,
        md5_checksum=digest,
    )
    task_id = await post_task_execution(tasks_api, EXEC_ARTIFACT_TASK, meta)
    if task_id is None:
        raise RuntimeError("Tasks API did not return a task history id")
    return task_id
