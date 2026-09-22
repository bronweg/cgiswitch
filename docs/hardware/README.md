# Hardware evidence index

These reports are dated observations with a stated device, firmware, scope,
and result. They do not replace the [validation methodology](../HARDWARE_VALIDATION.md).
Unit tests establish software behavior against fixtures and mocks. Hardware
evidence is limited to the device and firmware named in each row.

| Date | Report | Device and firmware | Scope | Result |
| --- | --- | --- | --- | --- |
| 2026-09-17 | [Read-only validation](2026-09-17-ONT-S207CW-62TS-SE-readonly.md) | Operator-identified ONT-S207CW-62TS-SE; V100SP11240725 | Identity, ports/VLANs, backup download and Web UI comparison | PASS for observations; overall validation incomplete |
| 2026-09-17 | [Controlled preflight](2026-09-17-controlled-preflight.md) | Same lab device; V100SP11240725 | Topology and baseline gate | INCOMPLETE; paused before preview/write |
| 2026-09-17 | [Controlled live validation](2026-09-17-controlled-live.md) | Operator-identified ONT-S207CW-62TS-SE; V100SP11240725 | Disposable VLAN and isolated-port lifecycle | PASS for controlled configuration and baseline restoration after permit-range parser correction; manual backup restore, natural expiry and traffic tests not performed |
| 2026-09-17 | [Management CGI discovery](2026-09-17-management-cgi-discovery.md) | Operator-identified ONT-S207CW-62TS-SE; V100SP11240725 | Management, user, system form discovery and save envelope | PASS for documented discovery scope |
| 2026-09-17 | [Management network transition](2026-09-17-management-network-transition.md) | Operator-identified ONT-S207CW-62TS-SE; V100SP11240725 | Controlled static IP transition, persistence and restoration | PASS for controlled transition; automatic persistence disproven |
| 2026-09-17 | [Credential transition](2026-09-17-credential-transition.md) | Operator-identified lab device; V100SP11240725 | Disposable credential change, save, reboot persistence | PASS for tested sequence |
| 2026-09-18 | [Bootstrap validation](2026-09-18-bootstrap-validation.md) | ONTi ONT-S207CW-62TS-SE; V100SP11240725 | Ansible bootstrap, idempotence, persistence, restoration | PASS for reported sequence; reboot responses were lost and verified by readback |

## Evidence boundaries

The source tree also contains fixture and unit-test evidence. CI runs language,
Ruff, Mypy, pytest, Python build, collection build, installed collection docs,
and example syntax checks on Python 3.11, 3.12, and 3.13. Those checks establish
reproducible software behavior and packaging, not hardware compatibility.

Raw hardware output, private variables, credentials, cookies, and backups are
kept outside committed reports. The dated reports retain their historical
scope and limitations; a later report does not silently upgrade an earlier
one.
