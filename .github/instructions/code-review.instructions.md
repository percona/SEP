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
