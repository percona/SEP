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
    MSG="PagerDuty alert triggered on inventory sync item failure"
```

This creates `changelog.d/SEP-503.added.md` containing just the description.
Commit the file as part of your PR. Skip the step entirely for purely internal
changes (CI, refactoring, tooling, docs) that have no user-visible effect.

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

## What happens at release time

The release-notes process assembles the fragments that belong to the release's
Jira fix version into a new `[vX.Y.Z] - YYYY-MM-DD` section in `CHANGELOG.md`,
updates the compare-link footer, and deletes the consumed fragment files.
Fragments for work merged after the release scope was locked remain in
`changelog.d/` and flow into the next release automatically.
