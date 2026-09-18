# Hardware validation runbook

This guide covers controlled configuration and bootstrap validation.
`tools/hardware_validate.py` handles the VLAN/port checks.
It does not record a result. Dated results and their scope are indexed in
[hardware evidence](hardware/README.md). The project remains Alpha until a
maintainer makes a separate decision supported by evidence.

## Safety boundary

Use a lab switch or approved maintenance window, an isolated test port, a
disposable VLAN range, and an independently tested recovery path. Identify the
management port before any write and exclude it from desired state. Stop if
the topology, recovery path, baseline, or disposable scope is uncertain.

Supply credentials only through `JTCOM_USERNAME` and `JTCOM_PASSWORD`; never
put them in commands, JSON, shell history, reports, or logs. Use a new private
output directory under ignored `hardware-evidence/` or outside the checkout.
The runner refuses an existing output directory and creates its leaf with
restricted permissions. Redact device identifiers, addresses, cookies, tokens,
and backups before committing observations.

## Install and inspect the runner

```bash
python -m pip install -e '.[dev]'
python tools/hardware_validate.py --help
```

The runner accepts an explicit base URL with `http://` or `https://`, without a
path, query, fragment, or embedded credentials. HTTPS verification is enabled
by default; `--insecure` only disables certificate verification.

## Read-only baseline

Record model, hardware and firmware details, operator, time zone, repository
SHA, management path, test and management ports, recovery path, and the UI
baseline. Then run:

```bash
python tools/hardware_validate.py read \
  --url https://<switch-host>/ --output <new-output-dir>
```

Compare `before.json` with the UI field by field: identity, ports, VLAN names
and membership, mode, administrative state, speed, and flow control. Preserve
the raw private output and commit only reviewed observations. A zero exit code
does not establish UI agreement.

## Backup and check-only gates

Download a backup into another new directory and prove through the device UI
that it is non-empty, not an error page, and restorable before writing:

```bash
python tools/hardware_validate.py backup \
  --url https://<switch-host>/ --output <new-output-dir>
```

Build a minimal desired JSON containing only disposable VLANs and the isolated
test port. Apply mode requires `--desired`, `--baseline`, `--test-port`,
`--management-port`, and one or more `--vlan-ids` in the range 2..4094:

```bash
python tools/hardware_validate.py apply \
  --url https://<switch-host>/ --output <new-output-dir> \
  --desired <desired.json> --baseline <initial-read-dir>/before.json \
  --test-port <test-port-id> --management-port <management-port-id> \
  --vlan-ids <disposable-vlan-id>
```

The baseline must match the current device identity, contain both selected
ports, and show disposable VLANs absent. Preview must affect only the declared
test port and VLAN IDs. Review `preview.json` and stop on any policy block,
unknown membership, unexpected port, or out-of-scope operation.

## Controlled writes

Writes require all three operator attestations and an explicit `--execute`:

```bash
python tools/hardware_validate.py apply \
  --url https://<switch-host>/ --output <new-output-dir> \
  --desired <desired.json> --baseline <initial-read-dir>/before.json \
  --test-port <test-port-id> --management-port <management-port-id> \
  --vlan-ids <disposable-vlan-id> --execute \
  --confirm-isolated-port --confirm-recovery-access \
  --confirm-backup-restorable
```

The helper refuses unsafe live scope: the test port must have no non-disposable
tags and exactly one untagged VLAN, either VLAN 1 or a declared disposable
VLAN. It does not restore backups, clean up after failures, or roll back. The
operator must recover manually using the reviewed procedure.

Test one concern at a time: create and rename a disposable VLAN; set access
membership; exercise an approved access/trunk transition; add and remove a
tag; test administrative state, speed, and flow; delete only an unused
disposable VLAN; and compare a final read with the original baseline. Use
`--allow-port-mode-change` and `--allow-untagged-move` only for the approved
isolated-port transition. Never enable delete-in-use for this runbook.

After every successful patch, verify fresh readback, preview the same input,
and require a no-op before the next case. The runner performs a repeat apply
check; record `changed: false`, no applied operations, and no backup side effect.

## Bootstrap and persistence

Use the public `bronweg.cgiswitch.jtcom_bootstrap` action for end-to-end tests.
Record identity, credentials privately, exact management settings, VLANs and
port settings before starting. Use temporary IP/password values and verify
controller reachability at both endpoints. Never configure the controller
network from the test. Obtain approval for disruptive writes and each reboot.

1. Run Ansible check mode and record predicted operations and zero configuration POSTs.
2. Run live bootstrap and independently verify identity, target credentials and
   exact management state; confirm the prior password is rejected.
3. Repeat: require changed=false, operations=[], zero password/IP POSTs and one saveconfig.
4. Reboot once, then verify uptime reset and persisted identity, credentials and
   management state. Repeat bootstrap with the same no-op and save expectations.
5. Restore the recorded management settings and credentials through the action,
   save, reboot once and compare the complete baseline again. Confirm temporary
   credentials are rejected and the temporary endpoint is no longer reachable.

Count requests without recording secret payloads. A lost reboot response must
not trigger another POST; establish the outcome through read-only observation.
Stop on unexpected or ambiguous state and report it before any corrective
mutation. The harness does not automate factory reset or backup restore.

## Session expiry

For read or backup only, `--idle-seconds N` waits in the same session before a
second read or download. Choose `N` from an observed device timeout; do not
assume waiting proves expiry. Never replay an ambiguous POST. If a safe
disposable expiry test is unavailable, record it as `INCOMPLETE`; do not
manufacture failure by unplugging management, changing global credentials, or
brute-forcing login.

## Evidence rules

Use [RESULTS_TEMPLATE.md](hardware/RESULTS_TEMPLATE.md) for each device and
window. Record sanitized commands, exit status, output paths, timestamps, UI
comparisons, recovery checks, and firmware-specific quirks. Use `PASS` only
when script output and independent UI/readback evidence agree; use `FAIL` for a
reproducible error and `INCOMPLETE` when a gate or comparison was not safely
completed. Keep raw evidence private and never convert an unrun check into a
pass by inference.
