## Summary

<!-- What does this PR do and why? Link to the Jira issue if not obvious from the branch name. -->

## Tested

<!-- Describe what you manually verified before requesting review.
     Example: "Created a MyDumper backup task, executed it, verified output file."
     For trivial changes (typos, CI config), write "N/A — [reason]". -->

## Checklist

<!-- Check items that apply. Leave unchecked items visible — reviewers use this too. -->

- [ ] New/modified functions have type hints and rST docstrings
- [ ] New tests added for new features or bug fixes
- [ ] All tests pass locally (`make test`)
- [ ] Pre-commit hooks pass (`make run-pre-commit`)
- [ ] Database migrations generated if models changed (`make makemigrations`)
- [ ] User-facing changes documented (README, inline help, UI text)
- [ ] Configuration changes documented with examples
