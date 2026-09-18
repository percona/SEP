# Diagnostic Script Authoring

Every script under `snippets/` is reachable two ways: by **search**, from the
Snippets catalog, and by **browsing symptoms**, from the Support diagnostics
category browser (`GET /api/apps/atw/`). Search reaches all of them. The browser
reaches only the scripts whose frontmatter says so, through one key:

```yaml
# diagnostic_categories:
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
#  - NOT_RESPONDING
```

This document is for the author deciding what that key should say.

## Every script declares the key

`diagnostic_categories:` is not optional, and that is the point. A script that
nobody had got round to categorising and a script deliberately kept out of the
browser used to look identical, so an omission could not be told from a
decision. Declaring the key everywhere makes the exclusion explicit, and makes
it checkable — see *What is enforced* below.

There are two valid spellings:

- **In the browser** — one or more category member names, as a YAML list.
- **Search-only** — the empty list, `# diagnostic_categories: []`, written on
  one line.

Do not write a bare `# diagnostic_categories:` with nothing after it. The
frontmatter is parsed with `yaml.safe_load`, which turns a valueless key into
`None` rather than an empty list; the reader logs it as a malformed value and
discards it. The script is then search-only by accident, with a warning in the
log as the only evidence — which is the ambiguity the key exists to remove.

## Deciding: symptom or cause

A script belongs in the browser when an operator who knows only the **symptom**
would reach for it. Every browser leaf is a symptom — "Server crashed — restart
not successful", "Writes are Blocked", "Overall Slowness" — and a script belongs
under one when running it *advances* the investigation: it extracts logs,
collects configuration, or summarises state broadly enough that the cause is
still unknown when you start.

A script is **search-only** when reaching it requires already knowing the
answer. A one-condition check named for the alert that fires it
(`mongodb_high_cache_miss_check.sh` → `MongoDBHighCacheMissRatio`) is reached
*from the alert*, which has already named the condition. Putting it in the
browser asks the operator to guess the cause before they have one.

Note what does **not** decide this: an `alerts:` binding. Most scripts in the
browser carry one too, so it neither qualifies nor disqualifies a script. What
discriminates is whether the script's own name and description state a *cause*
or a *symptom*, and whether its output narrows many causes or confirms one.

The corpus contains the boundary case that shows the rule is about the name and
not the filename suffix: `mongodb_blocked_writes_check.sh` is a `*_check.sh`
**and** is in the browser, because "writes are blocked" is itself a browser
leaf — its name states a symptom.

Most of the library is search-only, and that is the expected shape — well under
half the builtin scripts are in the browser.

## The permitted values

Write the **member name** — the left column below — not the display label. The
listing matches on the member name; a display label, or a name the taxonomy does
not define, places the script in no cell at all and is discarded silently.

The taxonomy is `ATWCategory` in `app/sep/apps/atw/categories.py`, twelve
members under three parents:

| Member name | Display label | Parent |
|---|---|---|
| `SERVER_CRASHED_RESTART_SUCCESSFUL` | Server crashed - Restart Successful | Crashes |
| `SERVER_CRASHED_RESTART_NOT_SUCCESSFUL` | Server crashed - Restart not Successful | Crashes |
| `OVERALL_SLOWNESS` | Overall Slowness | Performance Issues |
| `QUERY_TUNING_OPTIMIZATION` | Query Tuning / Optimization | Performance Issues |
| `NOT_RESPONDING` | Not Responding | Performance Issues |
| `WRITES_ARE_BLOCKED` | Writes are Blocked | Performance Issues |
| `PERFORMANCE_OTHER` | Other | Performance Issues |
| `TEMPORARY_STALLS` | Temporary Stalls | Performance Issues |
| `NATIVE_ASYNC_REPLICATION` | Native Asynchronous Replication | Replication High / Availability |
| `MULTI_SOURCE_REPLICATION` | Multi-Source replication | Replication High / Availability |
| `GALERA` | Galera | Replication High / Availability |
| `GROUP_REPLICATION` | Group Replication | Replication High / Availability |

A script may name several categories; it then appears under each of them.

## Which root the categories hang from

The browser groups categories under a **root** per technology. The root comes
from the script's `service_type:`, not from `diagnostic_categories:` —
`mysql`, `mongodb`, `postgresql`, `proxysql`, `haproxy` and `external` map to
their display labels, and a script with no `service_type` (or an unrecognised
one) lands under **Generic**.

`service_type` is not display-only: Alert Troubleshooting reads it too, and its
vocabulary is narrower than the browser's. `AlertServiceType`
(`app/sep/models.py`) defines only `generic`, `mysql`, `mongodb` and
`postgresql`, so a script declaring `proxysql`, `haproxy` or `external` is not
*moved* to some other alert group — it is dropped from Alert Troubleshooting
altogether, leaving one `Unknown service_type` warning in the log as the only
evidence.

On a script with one of those three roots a per-alert override is therefore
**required**, not optional: give every entry under `alerts:` its own
`service_type:` naming a value `AlertServiceType` defines, and that value
overrides the script-level one for that alert.
`snippets/proxysql_status.sh` is the worked example. The override is per entry —
setting it on one alert says nothing about the others on the same script — so an
alert added to such a script later needs its own line, and no test will tell you
when it is missing.

## What is enforced

`tests/app/sep/snippets/test_frontmatter_authoring.py` parses every file under
`snippets/` and checks it against the numbered authoring rules in its module
docstring. That docstring is the authoritative rule list; two of the rules are
this document's subject:

- **R12** — every script declares `diagnostic_categories:` with a list value,
  populated or empty.
- **R13** — every declared category names an `ATWCategory` member.

Both fail loudly at test time, which is the only place they can: neither an
omitted key nor an unknown category name produces a parse error, and the script
ships and runs normally with the browser simply never showing it.
