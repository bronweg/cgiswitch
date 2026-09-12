# Repository instructions

## Mandatory language rule

All committed content must be in English. Never add Cyrillic letters to any
tracked file, including source code, comments, docstrings, documentation,
examples, fixtures, generated artifacts, or agent instructions. Commit messages
and pull request titles and descriptions must also be in English.

Before committing, inspect the staged content for Cyrillic characters and fix
every occurrence. This rule applies to all agents and all future changes.

Enable the versioned local hooks with `git config core.hooksPath .githooks`.
Run `python3 tools/check_language.py --staged` to check the Git index, or
`python3 tools/check_language.py` to check tracked working-tree content.
The commit-message hook applies the same character check to commit messages.

## Refactoring discipline

Read the relevant production code and existing tests before making changes.
Describe the current behavior and the failure being addressed. Keep each change
within its requested scope; preserve VLAN and port semantics during structural
refactoring. Add regression coverage alongside functional fixes.

Keep the Ansible collection as the single supported Ansible interface. Do not
log credentials or session secrets, configure global logging in library code,
or silently substitute guessed values for unknown configuration state.

Use deterministic ordering for generated plans and results. Run Ruff, Mypy,
tests, and the Python and collection builds before considering work complete.
