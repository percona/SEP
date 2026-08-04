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

## What the fragment must say

The rules above govern the fragment's *form*. This one governs its *content*:
**state the shipped state per deployment, and the preconditions an operator must
satisfy — not merely the code default.** Write from the operator's position, not
the code's. Before committing the fragment, answer two questions:

1. **Does every deployment see this?** If any shipped artifact — the side-car
   image, a packaged profile, a default-on env — carries a different value than
   the code default, name it. `SETTINGS_OVERRIDE_ALLOWED_KEYS` defaults to
   unrestricted, but the embedded side-car image bakes an allowlist via
   `sidecar/settings.embedded.yaml`, so a fragment saying only *"unset (the default) leaves every deployment
   unrestricted"* tells the side-car operator the opposite of what they will see:
   a mostly read-only settings UI, with no signal in the release notes. When
   writing the fragment, account for the main axes of variation (process,
   deployment, install-state, version) and call out any non-uniform behavior.

2. **What must the operator already have?** Name settings that are *required*,
   not merely available. *"Per-deployment values are supplied as environment
   variables"* reads as optional configuration; `SECRET_KEY` and
   `SEP_DB_PASSWORD` are start-up preconditions, and a container missing them
   exits immediately. Name them, or point at the doc that carries the full
   contract.

Silence on either axis reads as *"works uniformly, needs nothing"* — the
operator's default assumption, and the one they act on.

This does not apply when the change behaves identically everywhere and adds no
precondition, nor to a new optional setting that defaults off uniformly — there
the code default genuinely is the operator's experience.

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
