# Development Guide

## Prerequisites

- Python 3.11+
- Git
- Ansible Core for collection builds (`pip install ansible-core`)

## Setup

```bash
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Upgrade packaging tools
pip install --upgrade pip setuptools wheel

# Install project + dev dependencies
pip install -e ".[dev]"

# Enable the repository language checks for local commits
git config core.hooksPath .githooks
```

Repository content and commit messages must be in English. Check staged
content with `python3 tools/check_language.py --staged`; CI also scans tracked
content. The repository URL above targets the pending maintainer rename.

## Running Tests

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

Run a specific test file:

```bash
pytest tests/unit/test_parser_vlan.py -v
```

## Code Quality

```bash
# Lint
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format
ruff format src/ tests/ galaxy/ examples/ tools/

# Type check
mypy src/
```

## Project Structure

```
cgiswitch/
  src/cgiswitch/
    switch.py          # JTComSwitch orchestration API
    client/            # HTTP session, request helpers, VLAN/port write ops
    parser/            # HTML → Python object parsers
    model/             # Typed dataclass models (VlanConfig, PortConfig, DeviceConfig …)
    utils/             # Diff/plan engines (vlan_diff, device_diff, port_diff, render)
    vendor/jtcom/      # JTCom-specific endpoint paths and field mappings
  galaxy/
    bronweg/cgiswitch/ # Ansible Galaxy collection (bronweg.cgiswitch, v0.1.0)
      galaxy.yml       # Collection manifest
      plugins/action/  # Action plugin
      plugins/modules/ # Module stub (ansible-doc / Galaxy)
      examples/        # Ready-to-run playbooks
  tests/
    unit/              # Unit tests for parsers, diff engines, and payloads
    fixtures/          # HTML snapshots from real devices
  examples/            # Runnable usage examples
  docs/                # Developer documentation
```

## Adding a New Read Helper

1. Identify the CGI endpoint in `vendor/jtcom/endpoints.py`.
2. Capture an HTML fixture in `tests/fixtures/`.
3. Add a parser function in `parser/`.
4. Add a typed model in `model/` if needed.
5. Implement the read helper in `switch.py` by calling the session and parser.
6. Write tests in `tests/unit/`.

## Building the Ansible Collection

The Ansible interface is provided by the `bronweg.cgiswitch` Galaxy collection.
Build it from the repository root with:

```bash
ansible-galaxy collection build --force galaxy/bronweg/cgiswitch
```

## Releasing



```bash
pip install build
python -m build
twine upload dist/*
```
