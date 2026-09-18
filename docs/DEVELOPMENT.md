# Development guide

Unit tests use fixtures and mocked requests. Device observations belong in the
[hardware evidence index](hardware/README.md).

## Setup

Use Python 3.11 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]" 'ansible-core>=2.15'
git config core.hooksPath .githooks
```

The development extra installs pytest, coverage, Ruff, Mypy, build, request
types, and mocked HTTP test support. All committed content, comments, fixtures,
generated files, and commit messages must be English. Check tracked content with:

```bash
python tools/check_language.py
python tools/check_language.py --staged
```

## Responsibilities

| Area | Responsibility |
| --- | --- |
| `src/cgiswitch/bootstrap/` | Identity-bound bootstrap discovery and transitions |
| `src/cgiswitch/switch.py` | Public Python API and apply orchestration |
| `src/cgiswitch/client/` | HTTP, sessions, backups, and CGI writes |
| `src/cgiswitch/parser/` | Strict firmware HTML parsing |
| `src/cgiswitch/model/` | Typed desired and read-state models |
| `src/cgiswitch/utils/` | Canonical state, normalization, planning, policy, and compilation |
| `src/cgiswitch/vendor/jtcom/` | JTCom endpoints and mappings |
| `galaxy/bronweg/cgiswitch/plugins/` | Ansible validation, action, module, and documentation |
| `tests/` | Unit tests, fixtures, and mocked orchestration |
| `tools/hardware_validate.py` | Explicitly scoped operator runbook helper |
| `docs/hardware/` | Evidence index and dated reports |

The Python core owns behavior and canonical models. The Ansible collection is
the supported Ansible interface and owns nested input validation. Parsers must
reject missing, malformed, ambiguous, or unknown device state. Do not infer
omitted values or log credentials and session secrets.

## Required checks

Run these commands from the repository root before handoff:

```bash
python tools/check_language.py
ruff check .
mypy src galaxy/bronweg/cgiswitch/plugins/module_utils tools/hardware_validate.py
pytest
python -m build --outdir /tmp/cgiswitch-python-dist
ansible-galaxy collection build --force --output-path /tmp/cgiswitch-galaxy-dist galaxy/bronweg/cgiswitch
ansible-galaxy collection install /tmp/cgiswitch-galaxy-dist/*.tar.gz --force
ansible-doc bronweg.cgiswitch.jtcom_config
ansible-doc bronweg.cgiswitch.jtcom_bootstrap
ansible-playbook -i localhost, --syntax-check galaxy/bronweg/cgiswitch/examples/*.yml
```

For focused work, run a specific test such as
`pytest tests/unit/test_parser_vlan.py -v`. Builds and syntax checks do not
prove compatibility with a physical switch.

## Change workflow

Capture a sanitized device response before changing a parser and add valid and
malformed fixture coverage. Keep canonical on-wire membership separate from
JTCom's access/trunk representation. Define policy, deterministic operation
ordering, and readback verification before adding a write. Preserve structured
failure context; the apply path has no transaction or automatic rollback.

Hardware procedures belong in [the validation runbook](HARDWARE_VALIDATION.md)
and their results belong in a dated report under `docs/hardware/`. Do not place
raw captures, credentials, cookies, backups, or private evidence in Git.
