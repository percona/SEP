# Changelog: same-release-cycle fix reconciliation

**Date:** 2026-04-22
**Status:** Design approved; ready for implementation planning.

## Problem

Users occasionally see a bullet under `### Fixed` in `CHANGELOG.md` that describes a bug they never experienced — because the bug itself was introduced by a feature that shipped in the *same* release. The "fix" refers to a regression against an unreleased sibling ticket, not against any published behaviour. When the release notes land, those entries are confusing noise: a fix for something users never saw.

The rule that such fragments should be skipped is already documented in several places (`changelog.d/README.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.claude/skills/implement-ticket/SKILL.md`, `.claude/skills/sep-code-review/SKILL.md`, `.claude/skills/sep-release-notes/SKILL.md`). In practice the rule still leaks because:

1. The rule is not uniformly stated across touchpoints (`CONTRIBUTING.md` and `.claude/skills/shared/conventions.md` both describe only the "purely internal changes" skip condition).
2. Nothing enforces the rule. `scripts/changelog.py check` validates fragment filenames and contents only; no check looks at Jira relationships, and no release-time safety net catches fragments that shouldn't have been created.

## Goals

- Fragments for same-release-cycle fixes must not appear in the rendered `CHANGELOG.md` for that release.
- Contributors should keep their current, lightweight, offline workflow (`make changelog-add` → pre-commit → merge). No new pre-commit Jira calls, no new mandatory metadata.
- Detection and drop decisions happen at release time, in a path that already has Jira access and a human reviewer in the loop.
- The rule is written once, authoritatively, and referenced consistently elsewhere — no further drift.

## Non-goals

- No automatic drop. Every drop is confirmed per-fragment by the release person.
- No Jira mutations from the release-notes flow (no labels, comments, or transitions driven by the drop decision).
- No change to `scripts/changelog.py`'s public behaviour (no new subcommands, no new flags, no new config). The script stays file-only.
- No pre-commit or `make changelog-check` extension. Those paths remain offline and deterministic.
- No new documentation files (no `docs/changelog-policy.md`, no FAQ). Edits only.

## Approach

Two independent tracks, each individually shippable.

### Track A — Docs unification

Single canonical source of the "when to skip a fragment" rule: `changelog.d/README.md` § "TL;DR — adding an entry", which already lists both skip conditions. Every other mention either short-references the canonical source or repeats the two bullets verbatim — no prose rewording allowed, since string drift is what caused the original inconsistency.

Load-bearing phrase to appear in every mention of the same-release-cycle exemption:

> regression from a sibling ticket in the same unreleased fix version — link it in Jira with `is caused by`.

That phrasing is what Track C's detection keys on: contributors are told to add a Jira `is caused by` link, and the release-time tooling reads that link.

**Edits required**

| File | Change |
|---|---|
| `CONTRIBUTING.md` (§ Changelog Fragments, line 43) | Replace the single "Skip the step entirely for purely internal changes..." sentence with both skip conditions plus a one-line pointer to `changelog.d/README.md`. |
| `.claude/skills/shared/conventions.md` (§ CHANGELOG Convention, line 146) | Same edit — both skip conditions, pointer to the README. Load-bearing because this file is auto-loaded by other code-touching skills. |
| `.claude/skills/implement-ticket/SKILL.md` (Phase 5b) | Already correct; add one sentence reminding the contributor to ensure the Jira `is caused by` link exists on the fix ticket before opening the PR, so the release-time check has something to key on. |

**Leave alone (already correct and will not be double-touched):**

- `changelog.d/README.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.claude/skills/sep-code-review/SKILL.md`
- `.claude/skills/sep-release-notes/SKILL.md` — Track C will edit this file; do not touch in Track A to avoid merge conflicts.

### Track C — Release-time reconciliation

Detection and drop logic live inside `.claude/skills/sep-release-notes/SKILL.md` § Step 3d (Changelog fragment validation). `scripts/changelog.py` is not modified. The skill already calls Jira for classification of *missing* fragments; we extend the same pass to scrutinise *present* fragments.

**Detection signal.** For each fragment file `changelog.d/SEP-X.<section>.md`:

1. Fetch SEP-X's issue links via the `jira` CLI.
2. Keep outward links of type `is caused by` whose target is a ticket SEP-Y.
3. For each such SEP-Y, fetch its Fix Version. A fragment is a drop *candidate* when SEP-Y's Fix Version equals the release being assembled and `CHANGELOG.md` has no `## [v<fix-version>]` header yet (the sibling is unreleased).

Only `is caused by` is read. No PR-body scraping, no commit-message heuristics, no fragment metadata. If the link is missing, the fragment stays — Track A's docs change is what drives authors to add the link.

**UX.** Step 3d's output gains a new bucket between "Extra fragments" and "OK":

```
Likely same-release-cycle fix fragments (candidates to drop):
  - changelog.d/SEP-1005.fixed.md
      is caused by: SEP-991 (Fix Version v0.12.0, unreleased)
      content: "Restore View Logs button via has_logs on TaskHistoryResponse"
  - changelog.d/SEP-1018.fixed.md
      is caused by: SEP-979 (Fix Version v0.12.0, unreleased)
      content: "Skip periodic-task dispatch when Nomad target host is unhealthy"
```

The skill then prompts the release person once per candidate:

```
Drop changelog.d/SEP-1005.fixed.md? (y/N/q)
```

- **`y`** — delete the fragment file immediately (before Step 4 calls `assemble`), record the drop in the Step 3d "Reconciliation summary" block, continue to the next candidate.
- **`N`** or empty — keep the file, record the kept-decision with a fixed default reason of `"reviewer kept"`. No follow-up prompt; the release person can edit the summary block later if they want more detail.
- **`q`** — abort the release flow. The release person fixes things up manually (adjust Jira links, retag fix version, etc.) and re-runs.

All drops happen before Step 4's `assemble` call, so the deletion flows through the normal release PR (`changelog-vX.Y.Z`) alongside the `CHANGELOG.md` update. No separate commit. No orphan files.

**Reconciliation summary in the Step 3d output.** The skill appends a short inline block at the end of the Step 3d report (not a separate file) that lists every fragment examined for the same-release-cycle check, the decision (`dropped` / `kept`), and the reason. The block is the audit trail for "why was this fragment dropped" and flows into the release person's scratch notes alongside the rest of Step 3d's output.

### Edge cases (all handled by the detection rule above)

| Case | Behaviour |
|---|---|
| Causing ticket already shipped in an earlier release | `CHANGELOG.md` has its `[vX.Y.Z]` header ⇒ bug reached users ⇒ not flagged, fragment stays. The "unreleased sibling" guard is load-bearing. |
| Causing ticket is in a different, future fix version | Fix Version mismatch ⇒ not flagged. The fix belongs in the current release independently. |
| Fragment ticket has `is caused by` → a ticket without a Fix Version | Treated as no match (not flagged). Surfaced in the report as an informational "unresolved link" line so the release person can chase it manually. |
| Causing ticket also got its own fragment | Only the *fix* ticket (source of the `is caused by`) is a drop candidate. The feature/added fragment is exactly what users need to see and is untouched. |
| Fragment ticket has multiple `is caused by` links | Any single matching target is enough. All matching targets listed in the report for transparency. |
| `jira` CLI unavailable or API error | Step 3d already requires Jira access; fail the step with a clear error and let the release person retry. No silent skip. |

## Files touched

**Track A**

- `CONTRIBUTING.md`
- `.claude/skills/shared/conventions.md`
- `.claude/skills/implement-ticket/SKILL.md`

**Track C**

- `.claude/skills/sep-release-notes/SKILL.md`

**Not touched**

- `scripts/changelog.py`
- `tests/scripts/test_changelog.py`
- `.pre-commit-config.yaml`
- `Makefile`
- `changelog.d/README.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.claude/skills/sep-code-review/SKILL.md`

## Testing / verification

Track A is documentation-only; verification is a read-through of the three edited files plus a grep to confirm the load-bearing phrase appears consistently. No unit tests.

Track C is a skill change, not code. Verification is:

1. Dry-run the updated `sep-release-notes` Step 3d against a past release (e.g. v0.10.3) where Jira links are known, and confirm the classification matches the expected output.
2. Dry-run against the current `[Unreleased]` set of fragments and inspect the candidate list for false positives/negatives.

No automated test is added for the skill; the skill is an LLM-driven workflow and is validated by dry-run against real data, consistent with the rest of the repo's skills.

## Rollout

Track A can ship in a single PR. Track C can ship in a follow-up PR. The two are independent and safe to interleave. First real use of Track C is on whichever release is assembled after it lands.

## Risks and mitigations

- **Authors forget to add `is caused by` links.** Same risk as today. Track A makes the instruction louder in three more places; `sep-code-review` already flags missing fragments and can naturally surface "this is a fix with no `is caused by` link — is it a same-release regression?" as a follow-up check, but that's explicitly out of scope for this change.
- **False positives** (detection flags a fragment that should stay). Per-fragment y/N prompt is the mitigation. Default is keep (`N`).
- **False negatives** (detection misses a fragment that should drop). The release person still sees the full fragment content in Step 3d and can delete it manually before Step 4. Same workflow as today, just with better surfacing.
- **Skill-side Jira fetch is slow.** Fragments are few per release (order of tens); a few Jira round-trips is acceptable at release time.

## Out of scope (explicitly deferred)

- Any form of contributor-facing enforcement (pre-commit, `make changelog-add` refusing a fragment, CI blocking a PR).
- PR-body / commit-message fallback signals.
- A `Caused-by:` metadata trailer in the fragment file itself.
- Automatic Jira comments or labels when a fragment is dropped.
- A `scripts/changelog.py check-siblings` helper.
- A `docs/changelog-policy.md` file.
