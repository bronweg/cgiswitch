# Management network transition validation

Status: controlled transition **PASS**; automatic persistence **DISPROVEN**;
persistence after explicit save **PASS**. Two authorized reboot experiments
established the required save behavior on this firmware.

Firmware: V100SP11240725 on the operator-provided ONT-S207CW-62TS-SE.
Identity was compared by MAC and serial against the earlier private baseline.
The controller network and HomeLab repository were not modified or read.
Only temporary lab addressing was used; production bootstrap is owned by
HomeLab IaC using the future public bootstrap API.

## Observations

The initially proposed test address was reported occupied by the operator and
was excluded. Another address on the existing factory subnet was selected;
ICMP received no replies and neighbor discovery reached FAILED before the run.
The transition also probes the target before writing and rejects a reachable
foreign identity or authentication/parse failure. Lack of a response alone is
not a guarantee that an offline device never uses that address.

1. Read original identity, management state, ports, and VLANs.
2. Send exactly one static network POST to the original endpoint.
3. Authenticate at the temporary target; verify the original MAC/serial and
   exact address, netmask, gateway, and disabled DHCP state.
4. Repeat the same transition at the target: `changed=False`, zero additional
   configuration POSTs.
5. Explicitly transition back with one POST. Verify the original management
   state and complete port/VLAN configuration match the baseline.

The successful POST envelope was accepted by the strict one-shot response
validator. No automatic mutation retry or rollback was used. Returning to the
baseline was a separately requested explicit transition, not failure handling.
A password change was not performed in this PR-11 run.

## Internal architecture

`client/ip_ops.py` owns reads and one-shot transport using the source-backed
payload builder. `bootstrap/network.py` owns identity checks, preflight, session
discard, bounded target polling, and exact readback. It is an internal primitive;
no bootstrap API is exported yet, and `JTComSwitch.apply()` is unchanged.

A lost POST response triggers observation, never another configuration POST.
Wrong identity, malformed state, rejected authentication, or mismatched final
configuration fails closed. Errors retain stage, write-attempt status, verified
identity, endpoints, and sanitized underlying error type; raw exception messages
and request data are withheld. Local session discard sends no logout to an
endpoint that may already belong to another device.

IPv4 desired validation rejects malformed values, invalid prefix types/ranges,
multicast/unspecified addresses, and gateway/subnet combinations rejected by the
observed UI. Only static IPv4 is supported; explicit HTTP(S) IPv4 URLs are
required and the target host must equal the desired address.

## Evidence and pending work

Private evidence:
`/home/ansible/hardware-evidence/pr11-network-transition/`, mirrored locally
under ignored `hardware-evidence/`. It contains source hashes, original/final
snapshots, transition/repeat/restoration results, and the two configuration POST
records. No passwords or production values are committed.

## Reboot without save: observed loss of management change

The temporary IP was applied and verified again. Exactly one `cmd=reboot`
POST was sent to `/syscmd.cgi`; the response was lost at transport level. The
request was not repeated. Subsequent endpoint probes found the same MAC/serial
at the original factory address, with the exact original address/mask/gateway.
The temporary target did not respond. Uptime fell from over eleven hours to
five seconds, confirming the reboot independently of the missing response.

A final read confirmed the original network state and full port/VLAN baseline.
No password change, restore, or controller network change was performed.
Evidence for this experiment is in the private sibling directory
`pr11-network-persistence/`, including before/after state, reboot response
failure type, endpoint observations, and the configuration POST trace.

The IP update does not persist automatically on this firmware.

## Save then reboot: persistence confirmed

With further operator authorization, the same temporary IP was applied and
verified, followed by one confirmed `saveconfig` and one reboot POST. After
reconnect, the same MAC/serial remained at the temporary address with exact
requested network state. Thus an explicit save is required for durable
management IP changes on V100SP11240725.

The original management address was then restored by an explicit transition
and saved. A final read confirmed the original management and full port/VLAN
baseline. No extra reboot was needed for cleanup. The original address after
this final save was not independently reboot-tested; save persistence had just
been proven using the temporary address.

Private evidence: `pr11-network-persistence-saved/` alongside the other runs,
including target save, reboot observations, exact state, restoration, and final
save. Production values, HomeLab inventory, and SOPS were not involved.

The future bootstrap workflow must save verified management changes at the
reached endpoint. The low-level transition itself deliberately does not infer
persistence or automatically reboot. Repeated already-desired transition
remains a no-op with no configuration POST.
