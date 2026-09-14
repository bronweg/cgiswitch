# Hardware validation checklist

This document is an operator runbook for validating the JTCom collection and
the `tools/hardware_validate.py` helper against a real switch. It records a
repeatable test plan; it does not claim that hardware testing has been run.
Every item starts as `NOT RUN`. Use `INCOMPLETE` when a prerequisite, result,
or recovery check is missing. The project remains Alpha independently of individual check results.

## Scope and prerequisites

Hardware validation requires an operator to provide the device and recovery
details. Do not begin a write test without all of the following:

- Model, hardware revision, serial or asset identifier, firmware version and
  build, management URL, browser used for UI comparison, operator, date/time
  and timezone, and repository code SHA.
- A dedicated lab switch or an approved maintenance window, an isolated test
  port, and a disposable VLAN ID range that cannot affect production traffic.
- An independent management path and a tested recovery path (console, out of
  band network, or a second approved operator path). Record how to recover
  before changing any port or VLAN.
- Current UI screenshots or exported facts, and permission to download and
  retain a configuration backup. Redact credentials, cookies, tokens, serial
  numbers, public addresses, and customer names from evidence.
- `JTCOM_USERNAME` and `JTCOM_PASSWORD` supplied through the environment. Do
  not put credentials in a command, JSON file, shell history, or report.

The management port is always excluded from write validation. The operator
must identify it explicitly. Hardware execution must stop if the test port,
management port, recovery path, or disposable VLAN IDs are uncertain. This
runbook does not authorize management-plane tests.

## Record device identity before testing

Mark each line `PASS`, `FAIL`, `INCOMPLETE`, or `NOT RUN`, and link the
evidence in `docs/hardware/RESULTS_TEMPLATE.md`.

- [ ] Status: `NOT RUN` — model and hardware revision recorded.
- [ ] Status: `NOT RUN` — firmware version and build recorded.
- [ ] Status: `NOT RUN` — browser name and version recorded for UI comparison.
- [ ] Status: `NOT RUN` — operator, UTC/local timestamp, timezone, and test
      window recorded.
- [ ] Status: `NOT RUN` — repository code SHA recorded (`git rev-parse HEAD`).
- [ ] Status: `NOT RUN` — management URL recorded without credentials.
- [ ] Status: `NOT RUN` — test port and management port recorded by switch
      identifiers and labels.
- [ ] Status: `NOT RUN` — recovery path, contact, and recovery procedure
      recorded and confirmed reachable.

## Establish and compare the baseline

1. Open the switch UI and record the device facts, port settings, VLAN list,
   VLAN names, tagged/untagged membership, port mode, admin state,
   speed/duplex, and flow control. Save sanitized screenshots or exports.
2. Run a read-only collection of facts with an explicit HTTPS or HTTP URL and
   a new output directory:

   ```text
   python3 tools/hardware_validate.py read --url https://<switch-host>/ --output <new-output-dir>
   ```

3. Independently compare the script output with the UI. A script exit code is
   not a pass by itself. Check identifiers, names, state, membership, mode,
   admin state, speed/duplex, and flow one field at a time. Record UI-only,
   API-only, malformed, or ambiguous values as `FAIL` or `INCOMPLETE` with
   sanitized evidence.
4. Preserve the original read output as the baseline. Do not normalize away a
   disagreement before recording it.

## Backup and restoration gate

Before any write, validate a backup and prove that the operator can restore it
through the switch UI. The helper does not invent or call a restore endpoint.

- [ ] Status: `NOT RUN` — download a backup into a new output directory:

  ```text
  python3 tools/hardware_validate.py backup --url https://<switch-host>/ --output <new-output-dir>
  ```

- [ ] Status: `NOT RUN` — confirm the backup is non-empty, is not an HTML login
      page, and is not a JSON/CGI error. Record byte count and a SHA-256 digest.
- [ ] Status: `NOT RUN` — use the switch UI's documented restore workflow on
      the target lab device, with the operator's recovery
      path ready. Confirm the restore is accepted and the device remains
      reachable.
- [ ] Status: `NOT RUN` — re-read facts after restore and compare them to the
      pre-restore baseline. Record any reboot, delay, or field loss.
- [ ] Status: `NOT RUN` — stop all write testing if the backup cannot be
      restored or recovery cannot be demonstrated.

## Check-only plan gate

Build a minimal desired JSON containing only the disposable VLAN and isolated
test port. The port field is `speed_duplex`, matching the Python model (Ansible uses `speed`);
do not use the Ansible `speed` key. Example shape (replace illustrative IDs
with approved values, and test one setting at a time):

```json
{
  "vlans": {
    "3000": {
      "name": "hw-test",
      "state": "present"
    }
  },
  "ports": {
    "2": {
      "access_vlan": 3000
    }
  }
}
```

Run the default check-only path first. Supply one or more disposable VLAN IDs
and identify both ports:

```text
python3 tools/hardware_validate.py apply --url https://<switch-host>/ \
  --output <new-output-dir> --desired <desired.json> --baseline <initial-read-dir>/before.json \
  --test-port <test-port-id> --management-port <management-port-id> \
  --vlan-ids <disposable-vlan-id> [<second-disposable-vlan-id>]
```

The check-only result must show a scoped diff. Confirm that every proposed
member reference is the test port and that no management port is present. A
plan that includes an undeclared VLAN reference, a VLAN used by another port,
an unscoped port, or an ambiguous mode is `INCOMPLETE` and must not be executed. Do not enable an
automatic delete-in-use override. Use `--allow-port-mode-change` or
`--allow-untagged-move` only when the operator has explicitly approved that
specific disposable-port change.

## Controlled write sequence

All writes use the explicit URL and a fresh output directory. The executable
path requires all three confirmations below; omit `--execute` until the
check-only plan has been reviewed:

```text
python3 tools/hardware_validate.py apply --url https://<switch-host>/ \
  --output <new-output-dir> --desired <desired.json> --baseline <initial-read-dir>/before.json \
  --test-port <test-port-id> --management-port <management-port-id> \
  --vlan-ids <disposable-vlan-id> --execute \
  --confirm-isolated-port --confirm-recovery-access \
  --confirm-backup-restorable
```

1. Create the disposable VLAN and verify its ID/name in the UI and in a fresh
   read.
2. Rename it and verify the new name, preserving the original ID.
3. Set membership on the isolated test port. Verify tagged/untagged behavior,
   access VLAN, port mode, admin state, speed/duplex, and flow in both the UI
   and a fresh read. Never test a link carrying management or production
   traffic.
4. Delete the disposable VLAN only after confirming no other member or port
   uses it. Verify absence in both views. If the device reports in-use, stop
   and record the exact sanitized response; do not force deletion.
5. Re-apply the same desired state. The second plan must be a no-op with no
   backup or write side effect. Record the plan and output directory.
6. Clean up any remaining disposable membership or VLAN objects and compare a
   final read with the original baseline. Investigate every difference,
   including implicit defaults and ordering changes.

## Authentication expiry checks

Exercise expiry only with a disposable, already-approved test session. Never
use expiry testing as a brute-force loop and never pull or alter management
configuration.

- [ ] Status: `NOT RUN` — allow a session to expire naturally, then issue a
      harmless authenticated GET/read. Confirm one re-authentication and one
      retry at most; record the request type and sanitized status.
- [ ] Status: `NOT RUN` — allow a separate session to expire naturally, then
      request a backup GET. Confirm the same one-retry behavior and validate
      the backup before retaining it.
- [ ] Status: `NOT RUN` — do not replay a POST after expiry unless it is an
      approved disposable operation with a known expiry point and known final
      state. Never retry an ambiguous write.
- [ ] Status: `NOT RUN` — if expiry repeats, stop and record the typed error;
      do not loop, brute force credentials, or pull management data.

## Evidence and completion rules

For every step, retain the command (with secrets and sensitive host data
removed), timestamp, exit status, output path, UI reference, and sanitized
observation. Use `PASS` only when the script result and independent UI check
agree. Use `FAIL` for a reproducible incorrect behavior. Use `INCOMPLETE` when
the check could not safely finish. Record firmware quirks separately with their impact and evidence.
Do not convert `NOT RUN` or `INCOMPLETE` to `PASS` by inference.

## Runner details and evidence handling

Install the checkout with `python -m pip install -e '.[dev]'` before running
`python tools/hardware_validate.py --help`. The helper uses the Python core,
not an Ansible task schema. A hostname must have an explicit scheme. HTTPS
certificate verification is enabled unless `--insecure` is supplied; that
option never changes HTTPS to HTTP.

Use a new directory beneath ignored `hardware-evidence/`, or a private directory
outside the checkout, for each invocation. Files contain raw device state,
exception messages, and potentially secret configuration backups. They are
not sanitized automatically. Never commit these artifacts. Copy only reviewed,
redacted observations into a results report. The runner creates its output
leaf directory with mode 0700 and refuses to reuse it.

Apply requires `--baseline` pointing to the initial read's `before.json`.
The baseline must be from the same device MAC and must show that every declared
disposable VLAN was absent. Both selected ports must be in the baseline and
current inventory. The helper rejects a disposable VLAN currently used by
another port and rejects out-of-scope desired fields and preview operations.
This cannot establish which physical link carries management or production:
operator isolation and recovery confirmations are essential, not proof supplied
by the script. Do not run concurrent UI or automation writers. Each apply reads
fresh state; a preview is not a reservation or a transaction.

The three confirmation flags attest to checks the operator already performed.
They do not perform a restore or prove recovery. `run.json` deliberately keeps
hardware validation status `INCOMPLETE`, even when the command succeeds.
`failure.json` preserves core apply context when available. Stop after any
failure; there is no automatic cleanup or rollback. Recover with the reviewed
manual procedure, then capture and compare the resulting state.

## Required individual write cases

Use a separate desired file, output directory, UI comparison, and result row
for each case. Never combine initial testing of membership, admin, speed, and
flow control into one patch. In the following examples, VLANs 3000 and 3001
and test port 2 are illustrative only; substitute the approved IDs everywhere.

| Case | Minimal desired input | Required observation |
|---|---|---|
| Create | `{"vlans":{"3000":{"name":"hw-a"},"3001":{"name":"hw-b"}}}` | Both new IDs/names in UI and readback |
| Rename | `{"vlans":{"3000":{"name":"hw-renamed"}}}` | Same ID, new name, membership unchanged |
| Access intent | `{"ports":{"2":{"access_vlan":3000}}}` | Untagged 3000, no tagged VLANs |
| Access to trunk | `{"ports":{"2":{"native_vlan":3000,"trunk_set_vlans":[3001]}}}` | Native 3000, tagged 3001; mode-change override required |
| Tagged remove | `{"ports":{"2":{"trunk_remove_vlans":[3001]}}}` | Tag removed; review effective mode/fallback and required override |
| Tagged add | `{"ports":{"2":{"trunk_add_vlans":[3001]}}}` | Tag restored; review mode-change override |
| Trunk to access | `{"ports":{"2":{"access_vlan":3000}}}` | All tags cleared; mode-change override required |
| Admin down | `{"ports":{"2":{"admin_up":false}}}` | Only isolated port disabled; management remains reachable |
| Admin up | `{"ports":{"2":{"admin_up":true}}}` | Isolated port re-enabled |
| Speed | `{"ports":{"2":{"speed_duplex":"100M/Full"}}}` | Use a device/link-supported token, compare configured and negotiated state |
| Speed reset | `{"ports":{"2":{"speed_duplex":"Auto"}}}` | Auto negotiation restored; compare UI and operational read |
| Flow on/off | `{"ports":{"2":{"flow_control":true}}}`, then `false` | Each configured value matches UI; do not infer traffic behavior from settings alone |

For access/native moves, add `--allow-untagged-move` only after reviewing the
change. For mode transitions, add `--allow-port-mode-change`. Overrides apply
to the configured isolated port only. The helper does not enable delete-in-use
or automatic VLAN creation.

After **each** successful patch, the runner captures a readback, previews the
same input again, and stops if it is not an unblocked no-op. It then performs a
second real `apply()` and records `repeat-apply.json`. Require `changed: false`,
`applied: []`, and `backup_file: ""`. Review every result independently; script
success does not establish agreement with the UI or actual packet forwarding.

Before deletion, restore the isolated port's original membership and settings
using the reviewed manual UI procedure, then verify the baseline. The harness
intentionally refuses references outside the disposable VLAN set, so it is
not a general baseline-restoration tool. Once neither disposable VLAN is used,
submit `{"vlans":{"3000":{"state":"absent"},"3001":{"state":"absent"}}}`.
Confirm deletion, repeat no-op, and final baseline equivalence. Record the
initial manual restore proof separately from final test cleanup.

## Natural session expiry with the helper

For `read` or `backup`, `--idle-seconds N` waits in the same authenticated
session before another read/download. Choose N from the observed device idle
session timeout; do not guess that a wait necessarily expired the session.
The read case saves `after-idle.json`. The backup case logs in, waits, then
downloads. Record evidence that expiry actually occurred and, if safely
available, sanitized device audit/request counts showing at most one login
and retry. The runner itself does not capture credentials, cookies, or request
bodies, and does not claim a retry count from successful output alone.

POST expiry and repeated expiry need an operator-approved way to invalidate
only the test session, such as a documented session revocation feature on an
isolated lab device. Do not guess a firmware endpoint or deliberately create
ambiguous transport failure during a write. If no safe mechanism exists, mark
these cases `INCOMPLETE` with the reason, retain mocked regression coverage as
separate evidence, and leave the hardware stage open. Do not brute-force
passwords, change global credentials, unplug management, or disable the
management port to manufacture failures.

## Completion gate

PR-09 is preparation only until this checklist has actual device evidence.
A reviewer must see real UI/readback comparisons, a successful manual restore,
all applicable scoped write/no-op cases, final recovery/cleanup, and explicitly
resolved discrepancies. Any unrun or unsafe deferred case remains visible as
`NOT RUN` or `INCOMPLETE`; it must not be silently waived. Keep project status
Alpha until a separate decision supported by hardware evidence.
