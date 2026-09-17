# Management network transition validation

Status: controlled transition **PASS**; reboot persistence **NOT TESTED**.
PR-11 is not hardware-complete until persistence is established with separately
authorized reboot. No reboot or save command was used in this run.

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

Persistence must be determined by changing to the temporary target, rebooting
without an inferred save policy, and identifying the device at the possible
endpoints. No persistence rule has yet been chosen for the future orchestrator.
