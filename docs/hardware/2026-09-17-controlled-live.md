# Controlled hardware validation: 2026-09-17

Status: **INCOMPLETE**; PR-09 remains draft and the project remains Alpha.
This report continues the [paused preflight](2026-09-17-controlled-preflight.md).

## Authorization and baseline

The operator confirmed that Port 4 carries management and all other ports
are physically free. The earlier inconsistent observations were explained by
a second identical switch on the network; the operator removed that conflict.
A fresh baseline showed only Port 4 linked (2500M/Full), VLAN 1 untagged on
all six ports, and no other VLANs. Port 2 was enabled, Auto speed, flow control
On. The device firmware is V100SP11240725; the operator-provided model is
ONT-S207CW-62TS-SE (the UI does not expose that model string).

The operator explicitly authorized live tests on this new lab switch with
factory reset as recovery. This superseded the runbook's manual restore gate
for this run; **backup restore remains untested**. No restore confirmation
was fabricated. A private scoped driver used the core API and membership
checks rather than asserting the CLI's `--confirm-backup-restorable` flag.
Management Port 4 and control-node networking were never configuration targets.

Disposable VLAN IDs: 3000 and 3001. Policy: safety port 4, mode changes and
untagged moves allowed for the isolated test. Deletion of in-use VLANs was
not enabled. Each step saved a check-only plan before real apply, with
executable operations restricted to these VLANs or Port 2. VLAN 1 membership
changes were limited to moving Port 2 away and restoring it afterward.

## Observed firmware behavior

Creation of both VLANs, rename of VLAN 3000, and access membership on Port 2
succeeded using revision `73877c1`. Each repeated real apply was a no-op.
Switching Port 2 to trunk (native 3000, tagged 3001) succeeded on the device,
but verification failed: the Web UI compressed its permit list to
`3000-3001`. The parser accepted individual IDs but not ranges. The structured
apply error retained the completed membership operation; further tests stopped.
A direct read of the actual UI confirmed `Port 2 | Trunk | -- | 3000 | 3000-3001`.

The parser correction expands bounded inclusive VLAN ranges, retaining strict
validation and existing list separators. Raw HTML and the original failure
remain in private evidence; this is a confirmed firmware formatting behavior,
not a transport or session-expiry failure.

## Completed controlled sequence

After validating the parser correction against the captured HTML and tests,
the corrected parser was deployed to the isolated control-node environment.
The remaining library was revision `73877c1`; `code.json` records the exact
parser file digest. Trunk readback and repeated real apply then passed without
further writes.

| Check | Result |
| --- | --- |
| Create VLANs 3000/3001 and rename 3000 | PASS |
| Access VLAN 3000 on Port 2 | PASS |
| Access to trunk, native 3000 / tagged 3001 | Write passed; initial verification failed; corrected readback passed |
| Trunk to access, tagged membership removed | PASS |
| Port 2 disable and enable | PASS |
| Port 2 speed Auto to 1000M/Full | PASS (configuration only) |
| Port 2 flow control On to Off | PASS |
| Restore Port 2: enabled, Auto, flow On, access VLAN 1 | PASS |
| Delete both unused disposable VLANs | PASS |
| Repeated real apply after every successful step | PASS: unchanged, no applied operations, no backup |
| Final complete port settings and VLAN membership vs baseline | Exact match |

No automatic rollback was used. Restoration was an explicit scoped apply,
followed by deletion after membership had been removed. Management remained
reachable. Independent extraction of saved Web UI tables confirmed port
settings after the corrected sequence and all six ports in access VLAN 1 at
the end. This was HTML comparison, not an interactive browser screenshot.
No additional firmware discrepancy was observed in this sequence.

## Evidence and remaining coverage

Private evidence on control-node:
`/home/ansible/hardware-evidence/pr09-live-20260917/`, with an ignored local
copy under `hardware-evidence/`. It contains the baseline, backup and digest,
per-step desired/preview/apply/repeat snapshots, and failure/UI evidence.
Credentials, device identifiers, raw pages, and binary backups are not committed.

Manual backup restore, natural session expiry, and traffic forwarding/link
negotiation on the disconnected test port remain unvalidated. Configuration
readback alone does not demonstrate packet forwarding or negotiated speed.
