# Credential transition validation

Status: **PASS** for the tested V100SP11240725 firmware. Tests used only a
random throwaway secret on the lab device, never HomeLab production values.
No SOPS file, HomeLab inventory, controller network, or restore operation was
accessed. Necessary test reboots were explicitly authorized by the operator.

## Observed sequence

1. Validate the same MAC/serial as the prior private hardware baseline.
2. Attempt target authentication first; the new throwaway credential was not
   active. Authenticate with the current credential and send one account POST.
3. Discard the old session without logout. Authenticate using the target and
   verify the same device. A fresh login using the old password was rejected.
4. Repeat the transition: unchanged, zero additional password POSTs.
5. Reboot without save. The original credential returned, proving the password
   change was not automatically durable.
6. Apply the target again exactly once, verify target authentication and old
   rejection, call the confirmed save operation, then reboot again.
7. The target credential survived the second reboot; original credentials were
   rejected and the original device identity and management network verified.

Both management IP and password changes require explicit save for persistence
on this firmware. No automatic reboot or save is embedded in the internal
credential primitive. The future bootstrap orchestrator must save completed
changes and report a failed persistence stage separately.

The switch now retains the temporary test password at the original factory
management address. It was not reset to the weak factory password: the observed
UI requires a new password of at least six characters. The throwaway secret is
stored in a private mode-restricted file on control-node for subsequent tests;
it is excluded from Git, report bodies, and structured results.

## Internal behavior and tests

`bootstrap/credentials.py` is an internal target-first transition component,
not a second public bootstrap API. It verifies expected MAC/serial at each
successful authentication, sends at most one password-change POST, and resolves
a lost response by fresh authentication. It fails if both old and new
credentials work. Rejected login is distinguished from auth failure during
identity readback; the latter cannot silently trigger a fallback mutation.

Credential response data is excluded from login errors; the low-level user
operation sanitizes transport failures. Dataclass repr, structured failures,
serialized results, and debug logs are covered by secret-leak regression tests.
Unit tests also cover both credentials rejected, wrong identity before writes,
CGI rejection, response loss with successful/failed reconciliation, immediate
session discard, and old-password ambiguity.

## Private evidence

`/home/ansible/hardware-evidence/pr12-credential-transition/` contains exact
source hashes, transition/repeat results, per-reboot credential observations,
and a mutation trace containing endpoint/command only, never password fields.
An ignored local copy is retained under `hardware-evidence/`.

The private `target-password` file is needed for subsequent controlled tests.
It must not be copied into public fixtures, issues, PR text, or logs. Production
bootstrap remains the responsibility of HomeLab IaC using the future public API.
