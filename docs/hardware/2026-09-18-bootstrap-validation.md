# PR-13 bootstrap hardware validation: partial results

## Scope and device

Tested revision: `64c6d65`. Device: ONTi ONT-S207CW-62TS-SE,
firmware V100SP11240725. Execution host: control-node. Identity was verified
against the previous private hardware evidence using MAC and serial; identifiers
and credentials are omitted from this report.

All bootstrap invocations used the installed
`bronweg.cgiswitch.jtcom_bootstrap` Ansible action. No internal transition
primitive was invoked by the validation harness. Controller networking was not
changed. Only temporary test values were used.

The pre-PR13 baseline is static 192.168.2.1/24, gateway 192.168.2.254,
with the previously saved PR-12 temporary credentials, six ports and one VLAN.
The target is temporary 192.168.2.250/24 with the same gateway and a separate
throwaway password. This is not a production bootstrap.

## Observed results

| Stage | Result | Password POSTs | IP POSTs | Save POSTs |
| --- | --- | ---: | ---: | ---: |
| Ansible check mode | changed=true; credentials and network planned | 0 | 0 | 0 |
| First live bootstrap | changed=true; both operations completed; saved | 1 | 1 | 1 |
| Repeat before reboot | changed=false; operations=[]; saved | 0 | 0 | 1 |

A transport-level observer recorded only endpoint paths and system command names,
never passwords, payloads, cookies or response bodies. Read-only checks enforced
a configuration POST prohibition. Counts include attempted transport calls.

Independent readback after the first live run verified:

- Target credentials accepted and original credentials rejected.
- Expected physical identity and exact target management state.
- Administrative port configuration and VLAN state unchanged from baseline.

## Reboot response loss and mandatory stop

One authorized reboot POST was sent. The response was lost and surfaced as
`JTComRequestError`. The harness stopped the mutation sequence immediately,
without retrying reboot or issuing another configuration POST.

A subsequent read-only observation successfully authenticated at the target.
Uptime changed from `0D 14H:21M:35S` before reboot to `0D 00H:00M:10S`.
This confirms that reboot occurred. The observation verified:

- Target IP and credentials persisted.
- Original credentials remained rejected.
- Physical identity and exact management network matched.
- Administrative port configuration and VLAN state matched the original baseline.

The missing reboot response is an observed firmware/transport behavior; it was
not treated as evidence that the reboot failed or as permission to repeat it.
No production code was changed to accommodate this observation.

## Remaining validation

The run is paused under the operator's stop-on-ambiguous-disruptive-response rule,
despite successful subsequent readback. The device remains at the temporary
target IP with the temporary target credentials.

The following steps have **not** been performed:

1. Post-reboot Ansible bootstrap with changed=false, zero password/IP POSTs,
   and exactly one saveconfig.
2. Restoration through the Ansible bootstrap action to the exact pre-PR13
   management network and credentials.
3. Saving that baseline, rebooting, and verifying its persistence alongside
   the original VLAN/port baseline.

PR-13 hardware validation is therefore incomplete. The PR remains Draft and
must not be merged before completion and final review. No factory reset,
backup restore, automatic rollback, or production/HomeLab values were used.

## Private evidence

Raw evidence is retained in
`/home/ansible/hardware-evidence/pr13-bootstrap/` on control-node, with an
ignored local archive under `hardware-evidence/pr13-bootstrap/`.

Evidence includes baseline and verification snapshots, private Ansible vars,
no-log playbook output, structured action results, per-stage POST traces and
the reboot attempt record. The private vars and password files must never be
committed or copied into PR text.
