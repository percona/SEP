# Contributing to SEP

- [Branching Strategy](#branching-strategy)
- [Pull Requests](#pull-requests)
- [Changelog Fragments](#changelog-fragments)
- [Setting Up Your Development Environment](#setting-up-your-development-environment)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
  * [Writing Tests](#writing-tests)
  * [Running Tests](#running-tests)
- [Getting Help](#getting-help)

## Branching Strategy

All development work should be done on feature branches derived from the main branch.
Branch names should follow the format `SEP-XXX`, taken from the [SEP Jira Board](https://percona.atlassian.net/jira/software/projects/SEP/boards/192).

Example:
```shell
git checkout main
git pull
git checkout -b SEP-123
```

## Pull Requests

When your feature or fix is ready, open a Pull Request (PR) from your feature branch (SEP-XXX) to the main branch. Ensure the PR description includes a representative summary of your changes.

All PRs must be reviewed and approved by at least one of our [CODEOWNERS](https://github.com/percona/SEP/blob/main/.github/CODEOWNERS).

## Changelog Fragments

If your PR contains a **user-facing** change (a new feature, a bug fix, a behaviour change, a security fix, or a configuration change), add a **changelog fragment** so the entry is picked up in the next release notes. Fragments live under `changelog.d/` at the repo root — each PR writes its own file, which means parallel PRs never collide on `CHANGELOG.md`.

To create a fragment, use the Makefile helper:

```shell
make changelog-add TICKET=SEP-XXX SECTION=<section> MSG="Brief description"
```

`<section>` is one of `added`, `changed`, `breaking`, `config`, `fixed`, or `security`. If your change belongs in multiple sections (e.g. it is both a Change and a Breaking Change), run the command once per section.

Skip the step entirely for purely internal changes (CI, refactoring, tooling, docs-only) that have no user-visible effect.

See [`changelog.d/README.md`](changelog.d/README.md) for the full format and examples. A pre-commit hook validates any fragments you touch, and `make changelog-check` / `make changelog-list` are available to inspect or preview them locally.

## Setting Up Your Development Environment

1. Clone the repository

```shell
git clone https://github.com/percona/SEP.git
```
or
```shell
git clone git@github.com:percona/SEP.git
```

2. Install the dependencies

Navigate to the project directory, create a virtual environment and install the required packages:

```shell
cd SEP
make venv
```

3. Install pre-commit hooks

We use pre-commit hooks to maintain code quality. Install them by running:

```shell
pre-commit install
```

This ensures that your code adheres to our linting and formatting standards before each commit (see [Coding Standards](#coding-standards)).

## Coding Standards

- **Linting and Formatting**:

We enforce code style guidelines using [Ruff](https://docs.astral.sh/ruff/). The rules are defined in the [pyproject.toml](https://github.com/percona/SEP/blob/main/pyproject.toml) file.

- **Docstrings**:

Use [reStructuredText (rST) docstrings](https://peps.python.org/pep-0287/) compatible with [Sphinx](https://www.sphinx-doc.org/en/master/usage/domains/python.html) for documentation.
All public modules, classes, methods, and functions should include docstrings.

Example:

```python
class OAuthToken(BaseModel):
    """Represent an OAuth token.

    :param access_token: The token used to access protected resources.
    :type access_token: str
    :param id_token: The token that contains identity information about the user.
    :type id_token: str
    :param refresh_token: The token used to obtain new access tokens after the
        current one expires.
    :type refresh_token: str
    :param token_type: The type of token, typically "bearer".
    :type token_type: str
    :param expires_in: The time duration after which the token expires.
    :type expires_in: TimedeltaSeconds
    :param scope: The scope of the access granted by the token.
    :type scope: str
    """

    access_token: str
    id_token: str
    refresh_token: str
    token_type: str
    expires_in: TimedeltaSeconds
    scope: str
```

- **Type Annotations**:

All functions and methods should include type annotations for parameters and return types.

Example:

```python
def deep_dict_update(main_dict: dict[Any, Any], update_dict: dict[Any, Any]) -> None:
    """Merge `update_dict` into `main_dict` recursively.

    Update `main_dict` with the contents of `update_dict` recursively. For each
    key in `update_dict`, if the key exists in `main_dict` and both values are
    dictionaries, merge them recursively. If the key exists in `main_dict` and
    both values are lists, prepend the list from `update_dict` to the list in
    `main_dict`. Otherwise, overwrite the value in `main_dict` with the value
    from `update_dict`.

    :param main_dict: The dictionary to be updated.
    :type main_dict: dict[Any, Any]
    :param update_dict: The dictionary containing updates to apply.
    :type update_dict: dict[Any, Any]
    """
    for key, value in update_dict.items():
        if (
            key in main_dict
            and isinstance(main_dict[key], dict)
            and isinstance(value, dict)
        ):
            deep_dict_update(main_dict[key], value)
        elif (
            key in main_dict
            and isinstance(main_dict[key], list)
            and isinstance(update_dict[key], list)
        ):
            main_dict[key] = update_dict[key] + main_dict[key]
        else:
            main_dict[key] = value
```

## Testing

### Writing Tests

New code usually means new tests. Make sure new features and bug fixes include corresponding tests.
[SEP v0.1.0-alpha](https://github.com/percona/SEP/releases/tag/v0.1.0-alpha) has a test coverage of over 50%, and our goal is to continually increase this percentage.

Tests are located in the [tests/](https://github.com/percona/SEP/tree/main/app/tests) directory and mirror the structure of the [app/](https://github.com/percona/SEP/tree/main/app/) directory. For example:
- For [app/models.py](https://github.com/percona/SEP/blob/main/app/models.py), the tests are in [tests/test_models.py](https://github.com/percona/SEP/blob/main/app/tests/test_models.py).
- For [app/api/routes/oauth.py](https://github.com/percona/SEP/blob/main/app/api/routes/oauth.py), the tests are in [tests/api/routes/test_oauth.py](https://github.com/percona/SEP/blob/main/app/tests/api/routes/test_oauth.py).

As you can see, test filenames are prefixed with a `test_`.

### Running Tests

Ensure all tests pass before pushing your code:

```shell
make test
```

## Getting Help

If you have any questions or need assistance, feel free to reach out:
- Open an issue on GitHub or on Jira.
- Contact one of the [CODEOWNERS](https://github.com/percona/SEP/blob/main/.github/CODEOWNERS) or anyone from the GAS team.
