# Controlled hardware preflight: paused before preview or writes

Historical attempt; subsequently continued in the [controlled live run](2026-09-17-controlled-live.md).

Status: **INCOMPLETE**. No configuration writes were made. The attempted
check-only sequence stopped at its baseline consistency assertion before
calling `apply()`. PR-09 remains draft.

## Topology and candidate scope

The control-node route to the switch uses `eth0`. The switch Web UI exposes a
MAC Search operation at `mac.cgi?page=search`, implemented as a read-only
`searchmac.cgi` POST. Searching for the control-node interface MAC in VLAN 1
returned a dynamic entry on **Port 4**. This identifies the current management
path from the execution host; Port 4 is excluded from test configuration.
The private evidence retains the route and search result. No control-node
network settings were changed.

Port 2 is a **candidate only**: it was administratively enabled, Link Down,
Auto speed, flow control enabled, and untagged in VLAN 1 with no tagged
membership. Physical isolation and recovery access still need operator
confirmation. Link Down alone is not an isolation guarantee.

VLANs 3000 and 3001 were absent and are proposed disposable IDs. Candidate
create/access/trunk input files were prepared privately. They have not been
executed or accepted as a completed check-only plan.

## Baseline changed during preparation

The first snapshot at 2026-09-17 09:28:33 UTC differed from the previous
read-only run:

- Ports 1, 4, and 6 were now active (1000M/Full, 2500M/Full, and 10G/Full).
- VLAN 10 named Management existed without tagged or untagged members.
- All six ports still had untagged membership in VLAN 1.

Before preview, a fresh state read was compared with this new snapshot.
It failed the VLAN equality assertion. A diagnostic read then showed only
VLAN 1; VLAN 10 had disappeared. Port configuration had matched the first
snapshot at the consistency check.

The preparation transport guard allowed only authentication/logout POSTs and
required read endpoints. The MAC Search request was a separate, observed UI
read operation. No VLAN or port configuration request was sent. The cause of
the state change is not established: operator confirmation of concurrent
activity is required before attributing it to external changes or firmware.
No parser behavior was changed in response to this observation.

## Private evidence

On control-node:

```text
/home/ansible/hardware-evidence/pr09-controlled-20260917T092833Z/
```

An ignored local copy uses the same run directory name under
`hardware-evidence/`. Artifacts include `before.json`, the authenticated UI
page, MAC Search UI/request result, `management-path.json`,
`unexpected-state-change.json`, and `preview-requests.json`. Local candidate
inputs are proposals only. Device addresses and MACs remain in private files.

## Required before resuming

1. Confirm other writers/UI changes are stopped and capture a stable new baseline.
2. Confirm the isolated physical test port and recovery path independently.
3. Complete the manual backup/restore gate, or explicitly resolve that gate
   with the operator before any live testing. A downloaded backup alone is
   not restore evidence.
4. Recheck disposable IDs, run and review check-only plans, then proceed only
   within the approved isolated scope.

VLAN/port write tests, repeated real apply, and final cleanup comparison have
not run. There is nothing from this attempt to roll back.
