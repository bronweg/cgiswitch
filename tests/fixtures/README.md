# Test fixtures

Fixtures are sanitized HTML inputs for parser tests. They make tests
repeatable; they do not establish compatibility with every JTCom firmware.

| Fixture | Source and use |
| --- | --- |
| `port_settings.html` | Captured JTCom Port Settings page |
| `port_stats.html` | Captured port operational status page |
| `vlan_static.html` | Captured static VLAN configuration page |
| `vlan_port_based.html` | Captured port-based VLAN page |
| `trunk_group.html` | Captured Trunk Group page |
| `trunk_lacp.html` | Captured LACP status page |
| `device_info.html` | Captured system/device information page |
| `management_ip.html` | Sanitized 2026-09-17 live GET of `/ip.cgi`, firmware V100SP11240725 |
| `user_account.html` | Sanitized 2026-09-17 live GET of `/user.cgi`, same firmware |
| `system_management.html` | Sanitized extracted system controls from the same discovery |
| `management_form_helpers.js` | Sanitized extracted shared form helpers |

The earlier page captures do not record a firmware revision; do not attribute
them to the hardware-validated firmware by inference.

The management fixtures use RFC 5737 example addresses and contain no MAC,
serial, credential, cookie, or session value. They establish UI field names
and serialization. The [management discovery report](../../docs/hardware/2026-09-17-management-cgi-discovery.md)
records which behavior was confirmed by live GET or POST; fixture tests alone do not establish mutation
support.

The `malformed_vlan_*.html` files are synthetic invalid responses. They cover
invalid VLAN IDs, access/native values, permit lists, and modes and must be
rejected rather than treated as missing or empty state.

## Capturing a new fixture

Capture the target page from an authenticated browser or controlled read,
record the device and firmware in a dated hardware report, remove secrets and
private identifiers, and add valid plus malformed parser tests. Do not commit
raw captures, backups, cookies, or unsanitized addresses.
