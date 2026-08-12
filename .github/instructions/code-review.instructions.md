---
applyTo: "**"
excludeAgent: "cloud-agent"
---

# Code Review — How to Review

These rules govern how a review is written. They are scoped to Copilot code review;
the cloud agent writes code rather than review comments, so it is excluded.

1. **Scope first, quality second.** The most common failure mode in code review is approving correct-but-unscoped code. Look at the diff holistically: are all touched files necessary for the stated purpose? Cosmetic rewording in files with no behavior change, function splits that weren't requested, constants extracted for single-use values, parameters added "for future flexibility", and "while I'm here" refactors all signal scope creep. Flag them even when the code is cleaner after — staying focused matters more than incidental polish.
2. **Cite the codebase, not rules.** When flagging a convention, reference an in-tree example (`app/core/utils/fields.py:NN`), not "the project standard" or any internal document. The audience for a review comment is the PR author — don't mention internal tooling, AI, or automation.
3. **Comment tone.** Suggest, don't demand. Prefer "Consider …" / "The codebase does X — see `file.py:line`" over "Violation", "Forbidden". Lead the top-level review with one or two specific strengths.
4. **Comment don'ts.** Never `@`-mention bot accounts (`@copilot`, `@dependabot`, `@coderabbitai`, `@github-actions`, …) — GitHub treats the mention as a wake signal and triggers a duplicate review run; name the bot without the `@` if you must. Never make first-person offers to the operator inside a posted comment ("happy to file a ticket", "let me know if you want me to …") — the only audience on the PR is the author; state any follow-up as a fact ("this belongs in a separate ticket").
5. **Typography — the renderer does not substitute.** GitHub performs no typographic substitution: whatever you type is what posts. Outbound review prose uses real Unicode punctuation — an em dash (U+2014) and a rightwards arrow (U+2192) — never `--` or `->`, which render literally as a double hyphen and an ASCII arrow. This is easy to get wrong for a structural reason rather than a careless one: the in-repo standards these reviews are written against are themselves in `--` register (correct for plain-text and rST-adjacent files no renderer touches), and the register bleeds into prose composed right after reading them. Three places where `--` and `->` stay **correct** and must not be "fixed": fenced code and ` ```suggestion ` blocks (verbatim file content — a Python rST docstring's `--` is an en dash to Sphinx), inline-code spans (`` `--fix` `` is a flag, not typography), and HTML comments, which are never rendered.
