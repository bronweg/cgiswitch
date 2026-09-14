# Hardware validation results

Copy this template for each device and test window. Replace placeholders only
with operator-verified values. The initial status for every check is `NOT
RUN`; permitted result labels are `PASS`, `FAIL`, `INCOMPLETE`, and
`NOT RUN`. A script exit code alone is not evidence of a pass.

## Run identity

| Field | Value |
|---|---|
| Overall status | `NOT RUN` |
| Model | `<operator value>` |
| Hardware revision | `<operator value>` |
| Serial/asset reference | `<sanitized operator value>` |
| Firmware version/build | `<operator value>` |
| Browser and version | `<operator value>` |
| Operator | `<operator value>` |
| Start/end time and timezone | `<operator value>` |
| Repository code SHA | `<git SHA>` |
| Management URL | `https://<redacted-host>/` |
| Test port | `<switch port ID and label>` |
| Management port | `<switch port ID and label>` |
| Recovery path tested | `<console/OOB/approved path>` |
| Disposable VLAN IDs | `<one or more IDs>` |
| Output directories | `<new directory per command>` |

## Safety gates

| Gate | Status | Evidence or operator note |
|---|---|---|
| Isolated test port identified | `NOT RUN` | `<link or file>` |
| Management port excluded | `NOT RUN` | `<link or file>` |
| Recovery access available and tested | `NOT RUN` | `<link or file>` |
| Baseline UI facts captured | `NOT RUN` | `<link or file>` |
| Baseline read captured | `NOT RUN` | `<command/output>` |
| Backup non-empty and non-error | `NOT RUN` | `<bytes, SHA-256, output>` |
| Backup restored through UI | `NOT RUN` | `<operator note/evidence>` |
| Post-restore facts match baseline | `NOT RUN` | `<comparison>` |

## Independent baseline comparison

Record the UI value and script value for each field. Add rows for every VLAN
and port in scope; do not claim agreement from a summary alone.

| Object/field | UI value | Script value | Status | Evidence/note |
|---|---|---|---|---|
| Device facts | `<value>` | `<value>` | `NOT RUN` | `<reference>` |
| Port `<test-port-id>` settings | `<value>` | `<value>` | `NOT RUN` | `<reference>` |
| VLAN `<vlan-id>` name/state | `<value>` | `<value>` | `NOT RUN` | `<reference>` |
| VLAN `<vlan-id>` membership | `<value>` | `<value>` | `NOT RUN` | `<reference>` |

## Command and result log

Use sanitized commands. Keep the exact output directory and exit code; do not
paste credentials, cookies, tokens, or unredacted device responses.

| Step | Command or action | Exit/status | UI comparison | Evidence |
|---|---|---|---|---|
| Read baseline | `hardware_validate.py read --url <redacted> --output <dir>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Backup | `hardware_validate.py backup --url <redacted> --output <dir>` | `NOT RUN` | `NOT RUN` | `<path/digest>` |
| Check-only plan | `hardware_validate.py apply ...` | `NOT RUN` | `NOT RUN` | `<path>` |
| Create disposable VLAN | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Rename disposable VLAN | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Set isolated membership | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Delete disposable VLAN | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Repeat apply/no-op | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |
| Cleanup and final read | `<command/action>` | `NOT RUN` | `NOT RUN` | `<path>` |

## Authentication expiry log

Expiry must be natural and limited. Record no password attempts. POST testing
is allowed only for an approved disposable operation with a known expiry point;
never replay an ambiguous write.

| Check | Status | Expected observation | Sanitized evidence |
|---|---|---|---|
| Natural expiry followed by harmless GET/read | `NOT RUN` | At most one re-authentication and retry | `<path/note>` |
| Natural expiry followed by backup GET | `NOT RUN` | At most one re-authentication and retry; valid backup | `<path/note>` |
| Approved disposable POST with known expiry | `NOT RUN` | No ambiguous replay; final state verified | `<path/note>` |
| Repeated expiry handling | `NOT RUN` | Typed error and stop; no loop or brute force | `<path/note>` |

## Disposable lifecycle and final comparison

| Assertion | Status | Evidence/note |
|---|---|---|
| VLAN created with expected ID and name | `NOT RUN` | `<reference>` |
| VLAN renamed and ID preserved | `NOT RUN` | `<reference>` |
| Membership limited to isolated test port | `NOT RUN` | `<reference>` |
| Access to trunk transition | `NOT RUN` | `<reference>` |
| Trunk to access transition and cleared tags | `NOT RUN` | `<reference>` |
| Admin down and up | `NOT RUN` | `<reference>` |
| Fixed speed and Auto reset | `NOT RUN` | `<reference>` |
| Flow control on and off | `NOT RUN` | `<reference>` |
| In-use deletion was never force-overridden | `NOT RUN` | `<reference>` |
| VLAN deleted and absent after refresh | `NOT RUN` | `<reference>` |
| Repeat apply produced a no-op | `NOT RUN` | `<reference>` |
| Final read compared with original baseline | `NOT RUN` | `<reference>` |
| No management or production state was changed | `NOT RUN` | `<reference>` |

## Quirks and disposition

Describe only sanitized, reproducible observations. Include model, firmware,
trigger, exact field or response shape, and whether the behavior is `FAIL` or
`INCOMPLETE`. Do not include credentials, cookies, session
secrets, full management addresses, or customer identifiers.

| Observation | Trigger | Status | Evidence | Follow-up |
|---|---|---|---|---|
| `<sanitized behavior>` | `<step and firmware>` | `NOT RUN` | `<path>` | `<owner/action>` |

## Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Operator | `<name>` | `<date>` | `NOT RUN` |
| Recovery owner | `<name>` | `<date>` | `NOT RUN` |
| Reviewer | `<name>` | `<date>` | `NOT RUN` |
