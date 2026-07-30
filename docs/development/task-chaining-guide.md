# SEP Task Chaining Guide

A **task chain** runs a sequence of SEP tasks one after another, where each step
starts only once the previous one has finished. Every step is a real
`TaskHistory` row with its own status, logs, target, and `executed_by` — so a
multi-step operation stays fully visible in the UI instead of hiding inside one
opaque script.

This guide covers when to reach for a chain, the exact rules the chain engine
enforces, and how to build the two shapes you are most likely to need: a
**same-host pipeline** and a **cross-host rolling operation**.

Code examples are lifted from the SEP tree; each carries an HTML comment naming
its source file and symbol (e.g.
`<!-- src: app/tasks/models.py :: TaskExecuteRequest -->`) so you can diff it
against the source as the code evolves. Docstrings are trimmed to their summary
line. Examples labelled `constructed` illustrate call shapes no current caller
uses verbatim.

---

## Vocabulary

| Term | Meaning |
|---|---|
| **Task** | A named, reusable definition (`Task` row) — a Nomad job spec or a Celery callable. Not a run. |
| **Task history** | One *run* of a task (`TaskHistory` row), carrying status, logs, and the `execution_request` it ran with. |
| **Chain** | An ordered list of task names dispatched one at a time, each on the previous one's completion. |
| **Root / parent** | Within one hop: the step that just finished and is dispatching the next. The first step of a chain is the root. |
| **Step** | One link in the chain — its own task history. |
| **Target** | The executor host a step runs on (a Nomad node name for Nomad-backed tasks). |
| **Private meta** | Chain bookkeeping stored in `execution_request.meta` under `_`-prefixed keys. Never forwarded as user meta. |

---

## Table of contents

1. [When to chain](#1-when-to-chain)
2. [Mental model](#2-mental-model)
3. [The request surface](#3-the-request-surface)
4. [Validation: what is rejected, and when](#4-validation-what-is-rejected-and-when)
5. [How a chain advances](#5-how-a-chain-advances)
6. [Recipe: a same-host pipeline](#6-recipe-a-same-host-pipeline)
7. [Recipe: a cross-host rolling operation](#7-recipe-a-cross-host-rolling-operation)
8. [Meta propagation: what carries forward](#8-meta-propagation-what-carries-forward)
9. [Failure semantics](#9-failure-semantics)
10. [Limits and guards](#10-limits-and-guards)
11. [Periodic chains](#11-periodic-chains)
12. [Gotchas](#12-gotchas)
13. [Testing a chain](#13-testing-a-chain)
14. [Debugging a chain that did not advance](#14-debugging-a-chain-that-did-not-advance)

---

## 1. When to chain

Chain when **every step deserves its own history row** and a later step must not
start until an earlier one has actually succeeded.

| You want | Use |
|---|---|
| Three ordered operations, each independently visible, retryable, and auditable | **A chain** |
| One operation whose internals happen to have phases | **One task** with multiple Nomad task-group steps |
| Fan-out — N independent runs, order irrelevant | **N separate dispatches**, no chain |
| Ordered work across *different* hosts | **A chain with `chain_targets`** ([§7](#7-recipe-a-cross-host-rolling-operation)) |
| Ordered work inside one Python process | **A Celery chain/chord** — not this mechanism |

The deciding question is *observability*, not ordering. If an operator will ever
ask "did step 2 succeed on node 3?", that step needs to be a chain link.

---

## 2. Mental model

There is **no chain object**. A chain is a linked list carried in the meta of
each run:

```
POST /execute/upgrade-mongo
  meta.chain_task_names = [B, C]
        │
        ▼
  TaskHistory(A)  meta._chain_task_names = [B, C]
        │  A reaches SUCCESS
        ▼
  TaskHistory(B)  meta._chain_task_names = [C]      ← A's remainder, minus B
        │  B reaches SUCCESS
        ▼
  TaskHistory(C)  meta._chain_task_names absent      ← chain complete
```

Three consequences fall out of this design, and most surprises trace back to one
of them:

* **The chain is resolved one hop at a time.** Nothing pre-creates the later
  steps. Task `C` is looked up by name at the moment `B` succeeds — if `C` was
  deleted meanwhile, the chain simply stops.
* **State travels in `meta`.** The pointer (`_chain_task_names`), the failure
  policy (`_chain_on_failure`), the per-step targets (`_chain_targets`), and the
  hop counter (`_chain_depth`) all live in `execution_request.meta`. The `_`
  prefix marks them private: [§8](#8-meta-propagation-what-carries-forward)
  explains why that prefix matters to you.
* **Only the root dispatch is validated by the API.** Later hops are dispatched
  internally. Validation happens once, up front
  ([§4](#4-validation-what-is-rejected-and-when)) — so a mistake that validation
  does not cover surfaces mid-chain as a log line, not an HTTP error.

---

## 3. The request surface

Chains are requested through the three `chain_*` fields on the execute-request
body:

<!-- src: app/tasks/models.py :: TaskExecuteRequest -->

```python
class TaskExecuteRequest(BaseModel):
    """Represent a task execution request."""

    meta: dict[str, Any] = {}
    payload: str | None = None
    eta: datetime | EmptyStrToNone = None
    anonymize_mask: int | None = None
    chain_task_names: list[str] | None = None
    chain_on_failure: bool = False
    chain_targets: list[str] | None = None
```

| Field | Meaning |
|---|---|
| `chain_task_names` | Ordered task names to run **after** the task you are dispatching. The dispatched task is step 0 and is *not* named here. |
| `chain_on_failure` | `False` (default) advances only on `SUCCESS`. `True` advances on any terminal status. |
| `chain_targets` | Per-step target overrides, parallel to `chain_task_names`. Omit for a same-host chain. |

`chain_targets` is index-aligned with `chain_task_names`, **not** offset by the
root:

```
chain_task_names = ["upgrade-mongo", "upgrade-mongo", "upgrade-mongo"]
chain_targets    = ["db-2",          "db-3",          "db-4"          ]
                     step 1           step 2           step 3
root: POST /execute/upgrade-mongo with meta.target = "db-1"
```

Four hosts are upgraded by a three-entry chain, because the root carries the
first one.

Post it to `POST /api/tasks/execute/{task_name}`:

```bash
curl -X POST https://sep.example.com/api/tasks/execute/upgrade-mongo \
  -H 'Content-Type: application/json' \
  -d '{
        "meta": {"target": "db-1", "mongo_release": "psmdb-80"},
        "chain_task_names": ["upgrade-mongo", "upgrade-mongo", "upgrade-mongo"],
        "chain_targets": ["db-2", "db-3", "db-4"],
        "chain_on_failure": false
      }'
```

The response is the **root** task history. The chain's later rows do not exist
yet — poll `GET /api/tasks/history/` (or the task-history UI) to watch them
appear.

---

## 4. Validation: what is rejected, and when

All chain validation happens once, on the root dispatch, in
`validate_chain_task_names`:

<!-- src: app/tasks/deps.py :: validate_chain_task_names -->

```python
async def validate_chain_task_names(
    session: AsyncSession,
    chain_task_names: list[str],
    parent_task: Task,
    chain_targets: list[str] | None = None,
) -> None:
    """Validate that all chain task names exist, no cycles are present, and owners/targets match."""
    if chain_targets is not None and len(chain_targets) != len(chain_task_names):
        raise HTTPBadRequestException(
            f"chain_targets length ({len(chain_targets)}) must match"
            f" chain_task_names length ({len(chain_task_names)})."
        )
    skip_target_check = chain_targets is not None
    parent_target = parent_task.data.get("Constraints", [{}])[0].get("RTarget")
    seen: set[str] = set() if skip_target_check else {parent_task.name}
    for name in chain_task_names:
        if name in seen:
            raise HTTPBadRequestException(
                f"Cycle detected in task chain: {name!r} already appears in the chain."
            )
        if not skip_target_check:
            seen.add(name)
        chain_task = await TaskManager.first(
            session,
            col(Task.deleted_at).is_(None),
            name=name,
        )
        if chain_task is None:
            raise HTTPNotFoundException(f"Chained task {name!r} not found.")
        if chain_task.owner != parent_task.owner:
            raise HTTPBadRequestException(
                f"Chained task {name!r} has owner {chain_task.owner!r},"
                f" expected {parent_task.owner!r}."
            )
        if not skip_target_check:
            chain_target = chain_task.data.get("Constraints", [{}])[0].get("RTarget")
            if chain_target != parent_target:
                raise HTTPBadRequestException(
                    f"Chained task {name!r} has target {chain_target!r},"
                    f" expected {parent_target!r}."
                )
```

| Rule | Applies | Failure |
|---|---|---|
| `len(chain_targets) == len(chain_task_names)` | when `chain_targets` set | `400` |
| Every chained task exists and is not soft-deleted | always | `404` |
| Every chained task has the **same `owner`** as the root | always | `400` |
| No task name repeats, and none equals the root's name | only **without** `chain_targets` | `400` |
| Every chained task's static `Constraints[0].RTarget` equals the root's | only **without** `chain_targets` | `400` |

**Why two rules switch off.** Both exist to catch a chain that would loop or
stray off its host — and both assume the chain stays on one host. Supplying
`chain_targets` states the opposite explicitly: each step runs on a host you
named, so `upgrade-mongo → upgrade-mongo → upgrade-mongo` is a rolling upgrade,
not a loop, and a per-step target legitimately overrides the static constraint.
The `_MAX_CHAIN_DEPTH` guard ([§10](#10-limits-and-guards)) remains as the
backstop against a genuine runaway.

**The owner rule is the one that bites.** `owner` is a plain string on `Task`,
and a mismatch is rejected outright. Every task in a chain must share one owner
— so seed a purpose-built owner for a chainable family of tasks (the Ansible POC
tasks all use `owner="ANSIBLE"`) rather than trying to chain across `BACKUPS`
and `CHECKSUMS`.

Once validated, the pointers are written into meta by `prepare_task_history`:

<!-- src: app/tasks/deps.py :: prepare_task_history -->

```python
    if execution_data.chain_task_names:
        await validate_chain_task_names(
            session,
            execution_data.chain_task_names,
            task,
            execution_data.chain_targets,
        )
        execution_data.meta["_chain_task_names"] = execution_data.chain_task_names
        execution_data.meta["_chain_on_failure"] = execution_data.chain_on_failure
        if execution_data.chain_targets:
            execution_data.meta["_chain_targets"] = execution_data.chain_targets
```

Note what is **not** validated: `chain_targets` entries are never checked
against the live executor host list. The root's target is (the execute route
rejects a target missing from `executor.get_hosts()`), but a typo in
`chain_targets[2]` passes validation and fails silently three steps later. See
[§14](#14-debugging-a-chain-that-did-not-advance).

---

## 5. How a chain advances

Every status sync asks whether this run should dispatch the next step:

<!-- src: app/tasks/celery.py :: maybe_dispatch_chain -->

```python
async def maybe_dispatch_chain(
    saved: TaskHistory,
    *,
    was_running: bool,
    await_annotations: bool = False,
) -> None:
    """Dispatch the next chained task when ``saved`` is in a chain-eligible state."""
    if not was_running:
        return
    meta = saved.execution_request.meta or {}
    chain_on_failure = meta.get("_chain_on_failure", False)
    is_terminal = saved.status.is_terminal()
    should_chain = saved.status == TaskHistoryStatusEnum.SUCCESS or (
        chain_on_failure and is_terminal
    )
    chain_task_names = meta.get("_chain_task_names")
    if should_chain and chain_task_names:
        await _dispatch_chained_task(
            chain_task_names[0],
            saved,
            chain_task_names[1:],
            await_annotations=await_annotations,
        )
```

Three conditions must all hold:

1. **`was_running`** — the run was `RUNNING` when this sync began. This is the
   idempotency guard: a re-sync of an already-terminal row will not re-dispatch
   the next step. A task that somehow jumps straight to a terminal status
   without ever being observed as `RUNNING` **will not chain**.
2. **A chain-eligible status** — `SUCCESS`, or any terminal status when
   `_chain_on_failure` is set.
3. **A non-empty `_chain_task_names`.**

`_dispatch_chained_task` then builds the next run — the heart of the mechanism:

<!-- src: app/tasks/celery.py :: _dispatch_chained_task -->

```python
        chain_targets = parent.execution_request.meta.get("_chain_targets")
        # Allow self-chaining when explicit per-step targets are provided — each
        # step runs on a different host (rolling upgrade pattern), so repeating
        # the same task name is intentional, not an accidental loop.
        if chain_task_name == parent.execution_request.task and not chain_targets:
            logger.warning(
                "Chained task %r is the same as the parent task; skipping self-chain",
                chain_task_name,
            )
            return
        next_target = chain_targets[0] if chain_targets else parent.execution_request.target
        # Start from the static task defaults, then overlay the parent's non-private
        # runtime meta so user-supplied params (e.g. restart_service, extra_vars)
        # propagate through every step of the chain without needing to be re-stated.
        chain_meta = dict(chain_task.data.get("meta", {}))
        chain_meta.update(
            {k: v for k, v in parent.execution_request.meta.items() if not k.startswith("_")}
        )
        chain_meta.pop("_chain_task_names", None)
        chain_meta.pop("_chain_targets", None)
        if remaining_chain:
            chain_meta["_chain_task_names"] = remaining_chain
        if chain_targets and len(chain_targets) > 1:
            chain_meta["_chain_targets"] = chain_targets[1:]
        chain_meta["target"] = next_target
```

Read that as a five-line contract:

* **Target** — head of `_chain_targets`, else inherit the parent's.
* **Remaining targets** — tail is forwarded; when it empties, the key is dropped
  and any further steps inherit.
* **Meta** — static task defaults first, parent's public runtime meta on top.
* **Pointer** — the remaining names are forwarded, or the key is dropped on the
  last step.
* **Identity** — `executed_by` and `anonymize_mask` are inherited from the
  parent, so a chain is attributed to the human who started it.

---

## 6. Recipe: a same-host pipeline

The simplest chain: three tasks, one host, stop on first failure.

**Requirements** — all three tasks share one `owner`, and all three declare the
same static `RTarget` (because you are not passing `chain_targets`, so the
static-target rule in [§4](#4-validation-what-is-rejected-and-when) applies).

```bash
curl -X POST https://sep.example.com/api/tasks/execute/snapshot-db \
  -H 'Content-Type: application/json' \
  -d '{
        "meta": {"target": "db-1", "retention_days": "7"},
        "chain_task_names": ["verify-snapshot", "prune-snapshots"]
      }'
```

What happens:

| Step | Task | Target | Meta it receives |
|---|---|---|---|
| 0 | `snapshot-db` | `db-1` | `retention_days=7` (as posted) |
| 1 | `verify-snapshot` | `db-1` (inherited) | `verify-snapshot`'s static meta **+** `retention_days=7` |
| 2 | `prune-snapshots` | `db-1` (inherited) | `prune-snapshots`'s static meta **+** `retention_days=7` |

`retention_days` reaches step 2 without being restated — that is the meta
overlay in [§8](#8-meta-propagation-what-carries-forward). If `snapshot-db`
fails, steps 1 and 2 never run and no history rows are created for them.

To run cleanup even on failure, set `chain_on_failure` — but note it is
chain-wide, not per-step ([§9](#9-failure-semantics)).

---

## 7. Recipe: a cross-host rolling operation

This is the shape `chain_targets` exists for: the same task, applied to a fleet,
one host at a time, gated on each host succeeding before the next is touched.

A MongoDB rolling upgrade is the canonical case. Order matters — hidden node
first (it serves no reads), then the secondaries, and the primary last:

<!-- src: app/sep/plugins/mongo_upgrade/routes.py :: start_upgrade -->

```python
@router.post("/upgrade", response_model=_UpgradeResponse, status_code=201)
async def start_upgrade(body: _UpgradeRequest, tasks_api: TaskAPI) -> _UpgradeResponse:
    meta: dict[str, Any] = {
        "target": body.target,
        "mongo_release": body.mongo_release,
    }
    if body.mongo_version:
        meta["mongo_version"] = body.mongo_version
    if body.restart_service:
        meta["restart_service"] = body.restart_service

    request: dict[str, Any] = {"meta": meta}
    if body.chain_targets:
        request["chain_task_names"] = ["upgrade-mongo"] * len(body.chain_targets)
        request["chain_targets"] = body.chain_targets

    history = await tasks_api.post("/execute/upgrade-mongo", json=request)
    return _UpgradeResponse(task_history_id=str(history["id"]))
```

The whole cross-host pattern is those two lines: repeat one task name once per
extra host, and hand over the host list.

<!-- constructed -->

```python
# Roll a 4-node replica set: hidden node first, primary last.
# The root carries db-4; chain_targets carries the remaining three.
ordered_hosts = ["db-4", "db-2", "db-3", "db-1"]  # hidden, secondary, secondary, primary
root, rest = ordered_hosts[0], ordered_hosts[1:]

await tasks_api.post(
    "/execute/upgrade-mongo",
    json={
        "meta": {
            "target": root,
            "mongo_release": "psmdb-80",
            "mongo_version": "8.0.12-7",
            "restart_service": "mongod",
        },
        "chain_task_names": ["upgrade-mongo"] * len(rest),
        "chain_targets": rest,
        "chain_on_failure": False,
    },
)
```

`chain_on_failure: False` is doing real work here — it is what makes this safe.
If `db-2` fails to come back up, `db-3` and `db-1` are never touched, so you are
left with a degraded-but-quorate replica set rather than a fleet-wide outage.

**Determine the order, do not assume it.** The POC discovers roles first (a
`discover-mongo` task per host reporting `primary` / `secondary` / `hidden` /
`arbiter`), then sorts the hosts before building the chain. Hardcoding "db-1 is
the primary" is wrong the moment an election happens.

**The task itself must be idempotent and self-verifying.** A rolling chain is
only as safe as its gate: the step must not report `SUCCESS` until the node is
genuinely back in service. The seeded `upgrade-mongo` playbook ends with a
readiness loop that polls `mongosh` until it answers, precisely so that
`SUCCESS` means "this node is serving again" and the next host is safe to take
down.

---

## 8. Meta propagation: what carries forward

Each step's meta is built in two layers:

```
chain_meta = dict(chain_task.data["meta"])            # 1. the step's static defaults
chain_meta.update(public keys of parent's runtime meta) # 2. the run's parameters win
chain_meta["target"] = next_target                     # 3. target always set last
```

The rule for you as a caller: **keys without a leading underscore travel; keys
with one do not.**

| Key | Travels? | Why |
|---|---|---|
| `mongo_release`, `restart_service`, `retention_days`, … | Yes | Public runtime meta — set once on the root, honoured by every step |
| `target` | Overwritten | Always replaced by the step's own target |
| `_chain_task_names`, `_chain_targets`, `_chain_depth`, `_chain_on_failure` | No (managed) | Private bookkeeping, rewritten per hop |

Two practical consequences:

**A step's static default loses to the root's runtime meta.** If
`prune-snapshots` declares `retention_days: 30` in its task definition and the
root was dispatched with `retention_days: 7`, the step runs with **7**. The
overlay is deliberate — it is what lets one parameter govern a whole chain — but
it means a step cannot hold a default that survives a root that sets the same
key.

**There is no per-step meta.** Every step sees the same public meta.
`chain_targets` is the only per-step dimension the mechanism offers. If step 2
genuinely needs a different `restart_service` than step 1, you cannot express
that in one chain — use separate tasks whose static meta differs, or dispatch
two chains.

Before this overlay existed, chained steps rebuilt meta from the static
definition alone, so `restart_service` and friends were silently dropped after
step 0 — every host after the first was upgraded with defaults. If you are
debugging an old chain that behaves differently per step, that is the change to
know about.

---

## 9. Failure semantics

`chain_on_failure` is a **single chain-wide flag**, captured on the root and
forwarded unchanged to every hop.

| `chain_on_failure` | Advances on |
|---|---|
| `False` (default) | `SUCCESS` only |
| `True` | Any terminal status — `SUCCESS`, `FAILED`, `STOPPED`, `STALE`, `LOST` |

Choose per chain, not per step:

* **`False`** for anything that changes infrastructure — rolling upgrades,
  restarts, schema changes. A failed step should stop the operation.
* **`True`** only for chains whose later steps are genuinely
  failure-independent: notification, cleanup, teardown, report generation.

There is no retry, no compensation, and no rollback. A chain stops or it
continues. If a step needs "retry twice then give up", that belongs in the task
(a Nomad `RestartPolicy`), not in the chain.

A stopped chain leaves **no trace of the steps that did not run** — there is no
`SKIPPED` history row. The evidence is the absence of rows plus the last row's
status.

---

## 10. Limits and guards

<!-- src: app/tasks/celery.py :: _MAX_CHAIN_DEPTH -->

```python
_MAX_CHAIN_DEPTH = 10
```

Each hop increments `_chain_depth`, and dispatch is refused once the parent's
depth reaches the limit:

<!-- src: app/tasks/celery.py :: _dispatch_chained_task -->

```python
    if parent.execution_request.meta.get("_chain_depth", 0) >= _MAX_CHAIN_DEPTH:
        logger.warning(
            "Chain depth limit (%d) reached for task %r; skipping chain to %r",
            _MAX_CHAIN_DEPTH,
            parent.execution_request.task,
            chain_task_name,
        )
        return
```

**A chain therefore runs at most the root plus 10 steps.** Longer chains are
accepted by validation and then truncate silently — a warning in the tasks-API
log is the only signal. A fleet of 15 hosts cannot be rolled in one chain; split
it, or raise the constant deliberately.

The other guard is the **self-chain check**: a step whose name equals the
parent's is skipped, *unless* `chain_targets` is present. That exception is what
makes `["upgrade-mongo"] * n` legal — without per-step targets, a task chaining
to itself on the same host is an infinite loop.

---

## 11. Periodic chains

A periodic task can carry a chain: `PeriodicTaskExecuteRequest` extends
`TaskExecuteRequest`, so `chain_task_names`, `chain_on_failure`, and
`chain_targets` are all accepted on the create-periodic-task body, and the chain
is validated at creation time:

<!-- src: app/tasks/routes.py :: create_periodic_task_for_task_name -->

```python
    if periodic_task.execute_request and periodic_task.execute_request.chain_task_names:
        await validate_chain_task_names(
            session, periodic_task.execute_request.chain_task_names, task
        )
```

**Known gap:** that call does not forward `chain_targets`. A periodic
cross-host chain is therefore validated as if it were same-host — cycle
detection and the static `RTarget` check both apply — so scheduling a rolling
`["upgrade-mongo"] * n` chain is rejected as a cycle at creation time even
though the identical chain is accepted on a one-off dispatch. Schedule
cross-host rolling operations as one-off dispatches until the periodic route
passes `execute_request.chain_targets` through.

---

## 12. Gotchas

| Symptom | Cause |
|---|---|
| `400 Cycle detected in task chain` on a deliberate repeat | No `chain_targets`. Cycle detection is only skipped when per-step targets are supplied ([§4](#4-validation-what-is-rejected-and-when)). |
| `400 has owner X, expected Y` | Chained tasks must share the root's `owner` string. |
| `400 has target X, expected Y` | Same-host chain whose steps declare different static `RTarget`s. Either align them or pass `chain_targets`. |
| Chain stops after 10 steps, no error | `_MAX_CHAIN_DEPTH` ([§10](#10-limits-and-guards)). Check the tasks-API log for the warning. |
| Step 2 ran with default parameters | Pre-overlay behaviour, or a key you expected to travel starts with `_` ([§8](#8-meta-propagation-what-carries-forward)). |
| Chain never advanced past a successful step | The run was never observed as `RUNNING`, so `was_running` was false ([§5](#5-how-a-chain-advances)). |
| Next step never appeared, nothing in the UI | A bad `chain_targets` host, or the task was deleted mid-chain. Both are log-only ([§14](#14-debugging-a-chain-that-did-not-advance)). |
| Chain continued after a failure | `chain_on_failure` was truthy. It is chain-wide and forwarded to every hop. |

---

## 13. Testing a chain

Chain behaviour is unit-tested against `_dispatch_chained_task` and
`maybe_dispatch_chain` directly — no Nomad required. The existing classes are
the templates to copy:

| Class | Covers |
|---|---|
| `TestDispatchChainedTask` | Target selection, remaining-target forwarding, meta overlay, private-key exclusion, fallback with no `chain_targets` |
| `TestSyncQueueItemChainDispatch` | End-to-end advance through a status sync |
| `TestMaybeDispatchChainMetaNone` | The `meta is None` edge case |
| `TestPrepareTaskHistory` (in `test_deps.py`) | Validation: meta injection, length-mismatch `400`, suppressed target check |

Assert on the **meta of the dispatched step**, since that is the entire
contract — target chosen, remainder forwarded, public keys carried, private keys
withheld:

<!-- src: tests/app/tasks/test_celery.py :: TestDispatchChainedTask -->

```python
    async def test_uses_first_chain_target_as_next_target(self) -> None:
```

Run them with:

```bash
make test PYTEST_PATHS="tests/app/tasks/test_celery.py tests/app/tasks/test_deps.py" COV=0
```

---

## 14. Debugging a chain that did not advance

Chain dispatch is **best-effort and log-only**. Every failure inside
`_dispatch_chained_task` is caught and logged, never surfaced to a user:

<!-- src: app/tasks/celery.py :: _dispatch_chained_task -->

```python
    except Exception:
        logger.exception(
            "Failed to dispatch chained task %r from parent %r",
            chain_task_name,
            parent.execution_request.task,
        )
```

So when a step is missing, there is no error to find in the UI — work the list
in order:

1. **Read the last step's meta.** `GET /api/tasks/history/{id}` →
   `execution_request.meta`. Is `_chain_task_names` still present and non-empty?
   Absent means the chain completed as far as it was told to go.
2. **Check the status against the policy.** Not `SUCCESS`, and
   `_chain_on_failure` false? That is a correct stop.
3. **Check `_chain_depth`.** At 10, you hit the limit.
4. **Check the next target exists.** `_chain_targets[0]` must be a live host in
   `GET /api/tasks/hosts/`. `chain_targets` is never validated against the host
   list, and an unknown node is the most common silent failure.
5. **Search the tasks-API log** for `Failed to dispatch chained task`,
   `Chained task ... not found`, `skipping self-chain`, and
   `Chain depth limit`. One of those five lines explains every stop this
   mechanism can produce.

---

## See also

* [SEP App Developer Guide](app-developer-guide.md) — building the app that
  dispatches these tasks
* [SEP Task Execution DFD](../customer/sep-task-execution-dfd/README.md) — how a
  single task reaches an executor
* `app/tasks/celery.py` — `maybe_dispatch_chain`, `_dispatch_chained_task`
* `app/tasks/deps.py` — `validate_chain_task_names`, `prepare_task_history`
