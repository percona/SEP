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

"""Define the step/state domain model and the :class:`InstallStrategy` seam.

No persistence and no execution here on purpose (PMM-15347/plan.md §4 item 9): this
module is pure planning logic, unit-testable without a database or a Nomad
connection. Two things are deliberately kept out of it, for the state machine (not
yet built) to own instead:

- **Running anything.** :meth:`InstallStrategy.build_step` returns a
  :class:`StepAction` -- data describing what a step needs, not an executed result.
  Turning that into a real Nomad job (the ``sudo raw_exec`` pattern
  ``exec-python-artifact`` already proves, PMM-15347/plan.md §2.2) is the state
  machine's job, so a strategy never touches the network or a host.
- **Persisting progress.** :class:`StepRecord`/:class:`HostBootstrapState` are the
  *shape* progress takes, not a database row -- SQLModel persistence for them is a
  follow-up (PMM-15347/plan.md §4 item 9: ``om_bootstrap`` owns durable state).

The dynamic-progress requirement lives in :meth:`InstallStrategy.plan_steps`: it
returns the ordered step *names* a given spec will run, computed from the spec
rather than fixed on the class, so a run's actual step list (which can differ
between strategies, and within one strategy between specs -- e.g. a TLS-enabled
spec adding a certificate step) is known before the first step starts. That is what
lets the UI render a real, run-specific progress list rather than a fixed one four
strategies would each have to fit themselves into.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

__all__ = [
    "BootstrapSpec",
    "HostBootstrapState",
    "InstallMethod",
    "InstallStrategy",
    "OperatingSystem",
    "StepAction",
    "StepRecord",
    "StepStatus",
]


class StepStatus(StrEnum):
    """One step's progress, as the UI renders it."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class InstallMethod(StrEnum):
    """Which :class:`InstallStrategy` a run uses.

    Only ``PACKAGES`` has an implementation
    (:class:`~app.sep.apps.om_bootstrap.strategies.packages.PackagesInstallStrategy`).
    ``DOCKER``/``PODMAN`` are named here so :class:`BootstrapSpec` and the future
    state machine have a closed set to switch on before a second strategy exists.
    """

    PACKAGES = "packages"
    DOCKER = "docker"
    PODMAN = "podman"


class OperatingSystem(StrEnum):
    """Target host OS. First implementation supports exactly these two."""

    UBUNTU = "ubuntu"
    ROCKY = "rocky"


class BootstrapSpec(BaseModel):
    """What one host's bootstrap needs to know to plan and build its steps.

    Deliberately minimal -- just enough to make :class:`InstallStrategy` concrete.
    The full Configure-step shape (replica set topology, member roles, TLS mode --
    PMM-15347/questions.md Q5/Q12) is a later design pass, not guessed at here.

    :param install_method: Which strategy plans and builds this host's steps.
    :param os: The target host's OS, from ``om_inventory``'s already-collected
        facts (PMM-15347/plan.md §2.1) -- not re-detected here.
    :param mongodb_version: The Percona Server for MongoDB version to install, e.g.
        ``"8.0"``. Selects the ``psmdb-<version>`` repository channel.
    :param replica_set_name: The replica set this host joins. ``rs.initiate`` and
        multi-host orchestration are the state machine's job, not a single host's
        strategy -- this field is what one host's own config file needs to name.
    """

    install_method: InstallMethod
    os: OperatingSystem
    mongodb_version: str
    replica_set_name: str


class StepAction(BaseModel):
    """What running one step actually requires -- the execution layer's input.

    Kept dispatch-mechanism-agnostic on purpose: every strategy's steps resolve to
    one of these, so the code that turns it into a real Nomad job (not built yet)
    has exactly one shape to consume regardless of which strategy planned it.

    :param command: The argv to run on the host.
    :param timeout_s: How long the execution layer should wait before treating this
        step as failed.
    """

    command: list[str]
    timeout_s: int = 120


class StepRecord(BaseModel):
    """One step's persisted-shape progress -- a host's, or a run's.

    The same shape serves both :attr:`HostBootstrapState.steps` (per-host) and
    :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRun.run_steps` (run-level,
    e.g. ``rs_initiate`` -- see :meth:`InstallStrategy.plan_run_steps`): neither
    context needs a field the other doesn't, so one type covers both rather than
    two near-duplicates.

    :param name: One of the names :meth:`InstallStrategy.plan_steps` (or
        :meth:`InstallStrategy.plan_run_steps`, or :meth:`InstallStrategy.plan_rollback_steps`)
        returned for this spec -- not a fixed enum, since the step list itself is
        per-strategy and per-spec (see the module docstring).
    :param status: This step's current status.
    :param started_at: When the execution layer began this step, if it has.
    :param finished_at: When this step reached a terminal status, if it has.
    :param detail: A human-readable outcome -- an error message on
        :attr:`StepStatus.FAILED`, or ``None`` while pending/running.
    :param task_history_id: The Tasks API history id backing this step's dispatch,
        while it is running -- the execution layer's own bookkeeping, not a
        strategy concern. Still just data describing progress, so it lives here
        rather than in a separate persisted-only sibling type: one shape for
        planning, persistence, and API responses alike.
    :param attempt_count: How many times this step has been dispatched.
        Incremented on every dispatch, including the first -- PMM's stepper reads
        this to enforce Adamo's decided retry policy (PMM-15347/questions.md Q8:
        retry once, then roll back) without needing a counter of its own, which
        would be lost on a leader failover. ``om_bootstrap`` only ever records the
        fact that a dispatch happened; deciding whether *another* one should is
        the stepper's call, not this field's.
    """

    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None
    task_history_id: int | None = None
    attempt_count: int = 0


class HostBootstrapState(BaseModel):
    """One host's progress through its planned steps.

    :param host: The node name being bootstrapped.
    :param steps: This host's steps, in the order :meth:`InstallStrategy.plan_steps`
        returned them -- the full list is known before the first one starts.
    :param rollback_steps: This host's teardown steps, in the order
        :meth:`InstallStrategy.plan_rollback_steps` returned them -- planned
        up front alongside ``steps`` so a fresh run already shows what rollback
        would consist of, even before anything fails. Every entry stays
        :attr:`StepStatus.PENDING` unless the stepper actually decides to roll
        this host back.
    :param finalize_steps: This host's post-coordination steps, in the order
        :meth:`InstallStrategy.plan_finalize_steps` returned them -- planned up
        front alongside ``steps``, but not dispatched until every run-level step
        has succeeded (PMM's stepper's call, mirroring how it gates run-level
        steps on every host's ``steps`` first -- see
        :meth:`InstallStrategy.plan_finalize_steps`'s own docstring for why this
        ordering exists at all).
    """

    host: str
    steps: list[StepRecord]
    rollback_steps: list[StepRecord] = []
    finalize_steps: list[StepRecord] = []

    @property
    def status(self) -> StepStatus:
        """Derive this host's overall status from its steps.

        Never stored directly -- a host's status is always a projection of its
        steps, so the two cannot drift apart the way an independently-set field
        could.

        :return: :attr:`StepStatus.FAILED` if any step failed,
            :attr:`StepStatus.RUNNING` if any step is running or still pending
            with an earlier step done, :attr:`StepStatus.SUCCEEDED` once every
            step has succeeded or been skipped, else :attr:`StepStatus.PENDING`.
        """
        statuses = [step.status for step in self.steps]
        if StepStatus.FAILED in statuses:
            return StepStatus.FAILED
        if StepStatus.RUNNING in statuses:
            return StepStatus.RUNNING
        if all(
            status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for status in statuses
        ):
            return StepStatus.SUCCEEDED
        if any(status != StepStatus.PENDING for status in statuses):
            return StepStatus.RUNNING
        return StepStatus.PENDING


@runtime_checkable
class InstallStrategy(Protocol):
    """One way to get MongoDB installed and configured on a host.

    A strategy owns *how*; the state machine (PMM's ``om`` service, driving as the
    HA-leader-only stepper) owns *when*, *whether the run as a whole should
    continue*, and *persisting progress* -- it does not know or care which
    strategy is running, only that every strategy answers these questions the
    same way. This is PMM-15347/plan.md §4 item 5's "abstracted pre-check/
    install/configure/test" requirement.

    Four parallel step lists, not one:

    - **Per-host** (:meth:`plan_steps`/:meth:`build_step`): everything a single
      host's own install needs, run independently per host.
    - **Run-level** (:meth:`plan_run_steps`/:meth:`build_run_step`): coordination
      that only makes sense once, for the whole run -- ``rs.initiate`` and
      creating PMM's monitoring user both need every member up first, and both
      only need to run *once* (MongoDB replicates a created user to every member
      automatically), not once per host. The stepper dispatches these to one
      designated host from ``hosts`` (index 0 by convention -- see
      :meth:`build_run_step`'s ``hosts`` parameter) once every per-host step has
      succeeded.
    - **Finalize** (:meth:`plan_finalize_steps`/:meth:`build_finalize_step`):
      per-host work that has to happen *after* run-level coordination has
      already succeeded, not before -- enabling MongoDB authorization is the
      motivating case: creating the first user reliably requires authorization
      to still be *off* everywhere at the time, because MongoDB's localhost
      exception is unreliable once a replica set already has more than one
      member (confirmed against a real multi-member run, not a theoretical
      concern -- once any privileged op on it fails once, the exception closes
      permanently for that mongod's whole lifetime, not just for one
      connection). So ``configure_mongod`` never enables authorization, and each
      host only turns it on for itself once ``create_pmm_monitoring_user`` has
      actually succeeded. The stepper dispatches these once every run-level step
      has succeeded -- the same per-host shape as :meth:`plan_steps`, just
      running after run-level steps instead of before them.
    - **Rollback** (:meth:`plan_rollback_steps`/:meth:`build_rollback_step`):
      one host's teardown, planned up front alongside its forward steps so a
      fresh run already shows what rolling back would do (Adamo's decided
      partial-failure policy, PMM-15347/questions.md Q8), even before anything
      fails.

    ``build_step`` and ``build_run_step`` both take a ``params`` mapping for the
    one thing a strategy cannot itself supply: per-run secrets (a keyFile's
    content, a generated monitoring-user password). PMM-15347/questions.md Q7
    decided these live durably in PMM's encrypted Postgres, not SEP's --
    ``params`` is how the stepper hands one to a single dispatch, transiently,
    without ``om_bootstrap`` ever persisting the plaintext in
    :class:`StepRecord`/:class:`~app.sep.apps.om_bootstrap.models.BootstrapRun`.
    """

    def plan_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's ordered per-host step names for ``spec``.

        Computed from ``spec`` rather than fixed, so the step list a run actually
        follows can vary with what the spec asks for (see the module docstring).
        Called once, before the first step starts.

        :param spec: The host's bootstrap spec.
        :return: Step names, in execution order.
        """
        ...

    def build_step(
        self,
        step_name: str,
        host: str,
        spec: BootstrapSpec,
        params: dict[str, str] | None = None,
    ) -> StepAction:
        """Build the action for one per-host step ``plan_steps`` named.

        Pure: given the same arguments, always returns the same action. Running it
        is the execution layer's job.

        :param step_name: One of the names this strategy's own :meth:`plan_steps`
            returned for ``spec``.
        :param host: The node name being bootstrapped.
        :param spec: The host's bootstrap spec.
        :param params: Per-dispatch values a step needs but cannot compute itself
            -- see the class docstring. ``None`` for a step that needs none.
        :return: What the execution layer needs to run this step.
        """
        ...

    def plan_run_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's ordered run-level step names for ``spec``.

        See the class docstring's "run-level" bullet. Called once, alongside
        :meth:`plan_steps`, before any host is touched.

        :param spec: The run's bootstrap spec.
        :return: Step names, in execution order.
        """
        ...

    def build_run_step(
        self,
        step_name: str,
        hosts: list[str],
        spec: BootstrapSpec,
        params: dict[str, str] | None = None,
    ) -> StepAction:
        """Build the action for one run-level step ``plan_run_steps`` named.

        :param step_name: One of the names this strategy's own
            :meth:`plan_run_steps` returned for ``spec``.
        :param hosts: Every host in this run, in the order the run was created
            with. Index 0 is the designated target this action runs *on* (e.g.
            ``rs.initiate``'s seed member) -- the same host every run-level step
            targets, so a strategy needing to name every member (``rs.initiate``)
            still has the full list to do so.
        :param spec: The run's bootstrap spec.
        :param params: See :meth:`build_step`.
        :return: What the execution layer needs to run this step.
        """
        ...

    def plan_finalize_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's ordered per-host finalize step names for ``spec``.

        See the class docstring's "finalize" bullet. Called once, alongside
        :meth:`plan_steps`, before any host is touched -- planned up front the
        same way rollback steps are, even though the stepper will not dispatch
        any of them until every run-level step has succeeded.

        :param spec: The host's bootstrap spec.
        :return: Step names, in the order finalize should apply them.
        """
        ...

    def build_finalize_step(
        self,
        step_name: str,
        host: str,
        spec: BootstrapSpec,
        params: dict[str, str] | None = None,
    ) -> StepAction:
        """Build the action for one finalize step ``plan_finalize_steps`` named.

        :param step_name: One of the names this strategy's own
            :meth:`plan_finalize_steps` returned for ``spec``.
        :param host: The node name being finalized.
        :param spec: The host's bootstrap spec.
        :param params: See :meth:`build_step`. ``None`` for a step that needs none.
        :return: What the execution layer needs to run this step.
        """
        ...

    def plan_rollback_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's ordered per-host rollback step names for ``spec``.

        See the class docstring's "rollback" bullet. Called once, alongside
        :meth:`plan_steps`, before any host is touched.

        :param spec: The host's bootstrap spec.
        :return: Step names, in the order rollback should apply them.
        """
        ...

    def build_rollback_step(
        self, step_name: str, host: str, spec: BootstrapSpec
    ) -> StepAction:
        """Build the action for one rollback step ``plan_rollback_steps`` named.

        :param step_name: One of the names this strategy's own
            :meth:`plan_rollback_steps` returned for ``spec``.
        :param host: The node name being rolled back.
        :param spec: The host's bootstrap spec.
        :return: What the execution layer needs to run this step.
        """
        ...
