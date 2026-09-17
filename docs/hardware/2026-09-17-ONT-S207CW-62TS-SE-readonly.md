# Read-only hardware evidence: ONT-S207CW-62TS-SE

Read-only phase: **PASS for the observations below**. Overall PR-09 hardware
validation: **INCOMPLETE**. Restore, configuration writes, repeated real apply,
and failure injection were not authorized or performed. The project remains Alpha.

## Device and execution identity

| Field | Observation |
|---|---|
| Date | 2026-09-17 UTC |
| Execution host | control-node |
| Core revision tested | `73877c1` |
| Operator-supplied model | ONT-S207CW-62TS-SE |
| Device type displayed in Web UI | Switch |
| Firmware version | V100SP11240725 |
| Firmware date displayed in Web UI | Jul 25 2024 10:40:09 |
| Hardware version displayed in Web UI | V5 |
| Python | 3.13.5 |
| Transport | HTTP to the operator-provided factory switch address |

The exact model is operator-provided: `info.cgi` exposes a generic Device Type,
not a model field. `DeviceInfo.model` correctly remains null. Firmware date and
hardware version are recorded from UI fields; they are not fields of the current
`DeviceInfo` model. MAC, serial, and IP were compared privately and are omitted
from this committed report.

The control node's existing networking was left unchanged. A dedicated virtual
environment and source archive were installed in the operator account. The
probe used the installed Python core, with transport guards permitting only
login/logout POSTs and the required GET endpoints. No configuration POST was
permitted. Credentials and cookies were not included in request logs.

## Observed state and independent comparison

Comparison used independent extraction of cells from the actual captured Web UI
HTML tables, rather than reusing the core parser's output as expected values.
It was not an interactive browser screenshot comparison. The private artifacts
retain the original HTML and a machine-readable comparison with 25 passing checks.

| Check | Result |
|---|---|
| Login | PASS |
| Device identity, firmware and uptime vs `info.cgi` | PASS |
| Port inventory and configured values vs `port.cgi` | PASS |
| Port link/speed/duplex vs `port.cgi` | PASS |
| VLAN IDs/names vs static VLAN table | PASS |
| Canonical memberships vs port-based VLAN table | PASS |
| Empty desired state in check mode | PASS: unchanged, unblocked, no operations |
| Backup download and validation | PASS: 3282 bytes |
| Manual backup restore | NOT RUN |
| Configuration changes and repeated real apply | NOT RUN |
| Session expiry/failure injection | NOT RUN |

All six ports are administratively enabled and configured with flow control on.

| Ports | Configured speed | Actual link state |
|---|---|---|
| 1, 2, 3 | Auto | Link Down |
| 4 | Auto | 2500M/Full |
| 5, 6 | 10G/Full | Link Down |

The UI's actual flow-control column is On on port 4 and Off on the other ports.
This does not conflict with configured flow control being On: the core's
`PortSettings.flow_control` represents the configured value, not that actual
column. Port 4 is the only observed active link. This is not a declaration that
it is safe to test, nor a verified identification of the management path.

Only VLAN 1 exists. Its name is empty. Ports 1 through 6 are Access ports in
VLAN 1, with no tagged membership. The UI displays `--` for their native/permit
fields, as expected for Access mode. Both the empty VLAN name and those Access
rows were handled correctly without parser changes.

The check-only call used an empty `DeviceConfig` and `check_mode=True`. It
returned `changed=false`, `blocked=false`, `operations=[]`, `applied=[]`, and
`backup_file=""`. This confirms a check-only no-op on the observed state; it is
not evidence of idempotency after a real configuration change.

## Backup and evidence custody

Backup SHA-256:

```text
e9a062a0b0d3f79de758184efad7040bbb985a6b1f37ccb08705bd0f3d529d8d
```

The downloaded bytes passed the existing non-empty/non-HTML/error-response
validation. No backup signature was inferred. Download success does not prove
restorability; no restore was attempted.

Private evidence on control-node:

```text
/home/ansible/hardware-evidence/pr09-readonly-20260917T082713Z/
```

A private local copy is under the ignored directory
`hardware-evidence/pr09-readonly-20260917T082713Z/`. The evidence includes:

- Original info, ports, static-VLAN and port-membership HTML responses.
- `read-results.json`, `ui-comparison.json`, and the validated `config.bin` backup.
- `check-only.json` and request traces, without request credentials or cookies.
- `manifest.json` with artifact SHA-256 digests.

Raw evidence includes device identifiers and a potentially secret backup. It
must not be committed. The local and remote evidence directories are private.

## Findings and remaining gates

No mismatch was found between parser/session behavior and the real firmware
for this read-only phase. No parser or session code was changed. Firmware-specific
observations above apply only to this device and firmware build.

Before any write phase, the operator must independently identify the management
path, select and isolate a safe test port and disposable VLAN IDs, establish
recovery access, and complete the manual backup/restore gate. All write-phase
and failure-injection checklist items remain open. This report does not authorize
those actions and does not complete PR-09.
