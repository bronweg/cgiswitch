# Development Guide

The project remains **Alpha**. Automated tests use saved HTML fixtures and
mocked requests; they do not establish compatibility with a particular device
or firmware. Hardware validation is still pending.

## Setup

Use Python 3.11 or later and Git. CI runs Python 3.11, 3.12, and 3.13.
The collection declares `ansible-core >=2.14.0`; CI installs
`ansible-core>=2.15` with a version compatible with each Python environment.
This is not a test matrix of every Ansible release.

```bash
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]" 'ansible-core>=2.15'
git config core.hooksPath .githooks
```

All committed content and commit messages must be in English. The local hooks
and CI mechanically reject Cyrillic; they do not detect every non-English
language. Check staged content with `python3 tools/check_language.py --staged`.

## Architecture

| Location | Responsibility |
|---|---|
| `src/cgiswitch/switch.py` | Public `JTComSwitch` API and apply orchestration |
| `src/cgiswitch/client/` | HTTP, authentication, backup validation, write payloads |
| `src/cgiswitch/parser/` | Firmware-specific HTML parsing |
| `src/cgiswitch/model/` | Typed configuration, state, connection, and policy models |
| `src/cgiswitch/utils/` | Canonical normalization, planning, policy, operation compilation, diffs |
| `src/cgiswitch/vendor/jtcom/` | CGI paths and firmware field mappings |
| `galaxy/bronweg/cgiswitch/plugins/action/` | Ansible controller execution and result mapping |
| `galaxy/bronweg/cgiswitch/plugins/module_utils/` | Ansible-specific nested input validation |
| `galaxy/bronweg/cgiswitch/plugins/modules/` | Module documentation and fallback stub |
| `tests/` | Unit tests, mocked orchestration, and HTML fixtures |
| `examples/` | Python usage scripts |
| `galaxy/bronweg/cgiswitch/examples/` | Ansible playbooks |

The Python core is independent of Ansible. The collection imports the core;
the core does not import collection input parsing. Unit tests resolve the
collection namespace against the checkout using `tests/conftest.py`.

Input validation, current-state reads, planning, policy, and payload compilation
precede backup and writes. Check mode still reads the device and validates the
request. It does not download a backup or write configuration. Changes are
applied directly through CGI requests: there is no transactional commit or
automatic rollback. Preserve structured failure context and the verification
snapshot when changing orchestration.

## Checks

Run from the repository root in the activated environment:

```bash
python tools/check_language.py
ruff check .
mypy src galaxy/bronweg/cgiswitch/plugins/module_utils tools/hardware_validate.py
pytest
python -m build --outdir /tmp/cgiswitch-python-dist
ansible-galaxy collection build --force --output-path /tmp/cgiswitch-galaxy-dist galaxy/bronweg/cgiswitch
ansible-galaxy collection install /tmp/cgiswitch-galaxy-dist/*.tar.gz --force
ansible-doc bronweg.cgiswitch.jtcom_config
ansible-playbook -i localhost, --syntax-check galaxy/bronweg/cgiswitch/examples/*.yml
```

For focused work, select a test file, for example
`pytest tests/unit/test_parser_vlan.py -v`. The default test command also
produces coverage reports. Syntax checks do not connect to a switch and do not
validate device-specific assumptions in example playbooks.

## Extending Device Support

Identify the CGI response and capture a sanitized fixture before changing a
parser. Add model and parser tests for both valid and malformed input. Do not
infer undocumented defaults or backup signatures. Different firmware may use
different fields, headers, or request semantics even on similarly named devices.

Before adding a write operation, define its canonical intent, policy checks,
preflight requirements, deterministic order, and verification behavior. Changes
to Ansible input belong in the collection layer. Keep documentation examples
consistent with its strict runtime validation.

## Release Status

Python package and collection versions remain `0.1.0`; package metadata remains
Alpha. Building artifacts is a local validation step, not a release or a claim
of hardware compatibility. A release requires a separate maintainer decision
and documented hardware validation results. Do not promote the maturity status
based only on mocked tests or successful builds.
