# PR-13 bootstrap hardware validation: final report

## Scope and device

Tested software revision: `64c6d65`. Device: ONTi ONT-S207CW-62TS-SE,
firmware V100SP11240725. Execution host: control-node. Identity was verified
against previous private hardware evidence using MAC and serial; identifiers
and credentials are omitted from this report.

All bootstrap invocations, including baseline restoration, used the installed
`bronweg.cgiswitch.jtcom_bootstrap` Ansible action. The validation harness did
not invoke internal credential or network transition primitives. The two
explicitly authorized reboots used the confirmed system command contract.
Controller networking was unchanged. Only temporary test values were used.

The pre-PR13 baseline was static 192.168.2.1/24, gateway 192.168.2.254,
with the previously saved PR-12 temporary credentials, six ports and one VLAN.
The test target was temporary 192.168.2.250/24 with the same gateway and a
separate throwaway password. This was not a production bootstrap.

## Exact Ansible results and configuration POST counts

| Stage | Result | Password POSTs | IP POSTs | Save POSTs |
| --- | --- | ---: | ---: | ---: |
| Initial check mode | changed=true; credentials and network planned | 0 | 0 | 0 |
| First live bootstrap | changed=true; both operations completed; saved | 1 | 1 | 1 |
| Repeat before reboot | changed=false; operations=[]; saved | 0 | 0 | 1 |
| Repeat after target reboot | changed=false; operations=[]; saved | 0 | 0 | 1 |
| Baseline restoration check mode | changed=true; credentials and network planned | 0 | 0 | 0 |
| Baseline restoration | changed=true; both operations completed; saved | 1 | 1 | 1 |

Every Ansible run succeeded. Both unchanged runs returned empty operations and
completed operations. Each mutation run completed `credentials:update` followed
by `management_network:update`. Every live run returned `persistence=saved`.

Across all recorded stages, including read-only observations, transport traces
contain exactly **two password POSTs, two IP POSTs, four saveconfig POSTs and
two reboot POSTs**. There were no other configuration POSTs or corrective writes.

The transport observer recorded only endpoint paths and system command names,
never passwords, payloads, cookies or response bodies. Counts include attempted
transport calls, including reboot requests whose responses were lost.
Read-only checks enforced a configuration POST prohibition.

## First bootstrap and target persistence

Independent readback after the first live run verified:

- Target credentials accepted and original credentials rejected.
- Expected physical identity and exact target management state.
- Administrative port configuration and VLAN state unchanged from baseline.

After the unchanged repeat, one authorized reboot POST was sent. Its response
was lost and surfaced as `JTComRequestError`. The harness stopped the mutation
sequence without retrying reboot. A subsequent read-only observation showed
uptime changing from `0D 14H:21M:35S` to `0D 00H:00M:10S`, confirming reboot.

That observation verified persisted target IP and credentials, rejection of
original credentials, expected identity, exact management state and unchanged
administrative port configuration and VLAN state.

The operator explicitly authorized continuation after reviewing those results.
The post-reboot Ansible run then returned changed=false and operations=[],
with zero password/IP POSTs and exactly one saveconfig.

## Exact baseline restoration and final persistence

Restoration inputs were derived from the private pre-PR13 baseline and
credential files. Ansible check mode planned the two expected transitions.
The live Ansible action restored 192.168.2.1/24, gateway 192.168.2.254, and the
pre-PR13 credentials, with exactly one password POST, one IP POST and one
saveconfig.

Independent readback verified the restored identity, exact management network,
accepted pre-PR13 credentials, rejected PR-13 target credentials, and unchanged
administrative port and VLAN baseline before the final reboot.

The final reboot was explicitly authorized and sent exactly once. Its response
was again lost (`JTComRequestError`); no retry occurred. Read-only observation
showed uptime changing from `0D 00H:40M:23S` to `0D 00H:00M:03S`.
A further full snapshot at `0D 00H:00M:13S` verified all of the following:

- Same physical identity and firmware.
- Static 192.168.2.1/24 and gateway 192.168.2.254 persisted.
- Pre-PR13 credentials accepted; PR-13 target password rejected.
- Administrative port configuration and VLAN membership exactly matched
  the saved pre-PR13 baseline.

At 2026-09-18T10:53:25Z, separate TCP probes to 192.168.2.250 on ports 80 and
443 both failed to connect, confirming the temporary management endpoint was
no longer reachable from control-node. No controller networking was changed.

## Observed firmware behavior and completion boundary

On this device/firmware, reboot can disconnect before a usable CGI response
arrives. A missing response does not establish failure to reboot and must not
trigger a second disruptive POST. Both reboot outcomes were established through
fresh authentication, identity/state verification and reset uptime.

The requested PR-13 end-to-end bootstrap, idempotence, persistence and exact
baseline-restoration validation is complete. No production code was changed
during this hardware run. The PR remains Draft pending final operator review;
this report does not authorize merge.

No factory reset, backup restore, automatic rollback, production/HomeLab values,
or SOPS access was used. The switch is left at the persisted pre-PR13 baseline,
not the temporary PR-13 target state.

## Private evidence

Raw evidence is retained in
`/home/ansible/hardware-evidence/pr13-bootstrap/` on control-node, with an
ignored local archive under `hardware-evidence/pr13-bootstrap/`.

Evidence includes baseline and verification snapshots, private Ansible vars,
no-log playbook output, structured action results, per-stage POST traces,
both reboot attempt records and final endpoint reachability observations.
Private vars and password files must never be committed or copied into PR text.
