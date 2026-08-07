# Changelog fragments

This directory holds per-PR **changelog fragments** that get assembled into
`CHANGELOG.md` at release time. Fragments exist so that parallel PRs never
collide on the same file — each PR writes a new file, so there is no merge
conflict on the `[Unreleased]` section.

## TL;DR — adding an entry

If your change is user-facing (a new feature, a bug fix, a behaviour change, a
security fix, or a config change), run:

```bash
make changelog-add TICKET=SEP-XXX SECTION=<section> MSG="Brief description"
```

Pass `FORCE=1` to overwrite an existing fragment for the same
`(ticket, section)` pair; without it the helper refuses to clobber.

where `<section>` is one of:

| Short name  | Renders as             |
|-------------|------------------------|
| `added`     | Added                  |
| `changed`   | Changed                |
| `breaking`  | Breaking Changes       |
| `config`    | Configuration Changes  |
| `fixed`     | Fixed                  |
| `security`  | Security               |

Example:

```bash
make changelog-add TICKET=SEP-503 SECTION=added \
    MSG="PagerDuty alert triggered on inventory sync item failure."
```

This creates `changelog.d/SEP-503.added.md` containing just the description.
Commit the file as part of your PR.

**Write the description as a complete sentence, ending in `.`, `!`, or `?`.** A fragment
is rendered verbatim as a release-note bullet, so whatever punctuation it carries
is what users read. `make changelog-add` appends a terminal period when the `MSG`
lacks sentence punctuation (recognising `.`, `!` and `?`, and looking past a trailing `)`, `]`,
`}`, quote or backtick), and tells you when it did — so a fragment edited by hand
is the only way to end up without one. Capitalise the first word; do not add a
`- SEP-XXX:` prefix, which assembly supplies.

**Skip this step when any of these applies:**

1. **Purely internal changes** — CI, refactoring, tooling, docs with no
   user-visible effect.
2. **Same-release-cycle fix** — the PR fixes a regression or behaviour
   change introduced by another ticket that shares this PR's Jira `Fix
   Version` and is itself still unreleased (no `[vX.Y.Z]` header for that
   Fix Version in `CHANGELOG.md`). Usually surfaces as a Jira `is caused
   by` link to a sibling ticket in the same version. The bug never
   shipped to users, so a fragment would add confusing "regression fixed"
   noise to release notes describing behaviour users never saw.
3. **Framework-spine-uniform surface** — a verb, query param, or field
   introduced once by a shared framework and inherited *identically* by
   every plugin that migrates onto it is documented once, when the
   framework ships it — not re-documented per migrating plugin. Add a
   fragment only for the plugin-specific delta (e.g. a request-body shape
   change unique to this plugin). Example: the `TaskExecutionApp` spine's
   `update=True` / `connectivity_check=True` flags (PUT verb,
   `check_connectivity` param, `connectivity_warning` field) shipped with
   the checksums pilot (SEP-1370); a later plugin migrating onto the same
   spine does not re-document them, but does add a fragment for, say, a
   request-body casing narrowing that only that plugin undergoes.

## What a fragment must say

A fragment is read by an operator deciding whether a change affects them and
when. Two things it must carry.

**Name the asymmetry.** When the change does not land uniformly — for some
installations and not others, for some processes and not others, or only after
a delay — say so. Silence on an asymmetric axis reads as "works uniformly".
Answer whichever of these three applies:

| Axis | The question to answer | Say this, not that |
|---|---|---|
| **Who** | fresh installs only, or existing installations too? | "reaches fresh installs and installer re-runs only; an existing installation keeps its rendered config until the installer runs again" — not "the new default applies" |
| **When** | at upgrade, at restart, or on the next occurrence of some event? | "an override lands on the next task the worker executes" — not "without a restart" |
| **Lag** | how long between the triggering action and the effect, and what happens to work started inside that window? | "worker-side refresh advances while tasks run rather than on a wall-clock interval, so an override has no fixed upper bound on when it lands and work enqueued in the meantime may still run against the old value" — not "takes effect immediately" |

**Pick the section from what the change *is*.** The work-item type decides only
once that answer is "a modification to behaviour that already shipped".

| Section | Use when |
|---|---|
| `added` | a surface that did not exist before — a new endpoint, image variant, CLI, published artifact, settings class. Applies whatever the work-item type says. |
| `breaking` / `security` / `config` | the change is primarily that, regardless of type. |
| `fixed` / `changed` | everything else. Both cover a modification to shipped behaviour, so the type is the tiebreak: Bug → `fixed`, Story → `changed`, even when two tickets do topically identical work. |

## File format

- **Filename:** `<TICKET>.<section>.md`, e.g. `SEP-503.added.md`.
- **Content:** one line of markdown per entry, with no `- SEP-XXX:` prefix
  (that is added automatically at assembly time).
- **Multiple sections per ticket:** create one file per section, e.g. a ticket
  that is both a Change and a Breaking Change has `SEP-937.changed.md` plus
  `SEP-937.breaking.md`.
- **Multiple entries in the same section:** the `make changelog-add` helper
  writes a single-line fragment. If you need more than one entry for the same
  `(ticket, section)` pair, edit the fragment file by hand and add additional
  lines — each non-empty line becomes its own entry in the rendered output.

## Preview and validation

```bash
make changelog-check    # validate all fragments (runs on pre-commit too)
make changelog-list     # print a CHANGELOG-style preview of what is pending
```

`make changelog-check` is also wired into pre-commit and runs automatically
whenever a file under `changelog.d/` is staged.

`make changelog-list` prints only the `### <section>` headers and their
bullets — it deliberately omits the `## [Unreleased]` header and the blank
lines that frame the section in `CHANGELOG.md`, so the output is a content
preview rather than a byte-for-byte slice of the old file.

## What happens at release time

The release-notes process assembles the fragments that belong to the release's
Jira fix version into a new `[vX.Y.Z] - YYYY-MM-DD` section in `CHANGELOG.md`,
updates the compare-link footer, and deletes the consumed fragment files.
Fragments for work merged after the release scope was locked remain in
`changelog.d/` and flow into the next release automatically.
