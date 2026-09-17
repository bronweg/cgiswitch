# Test Fixtures

This directory contains static HTML snapshots captured from real JTCom switch
web interfaces. They are used as inputs to the HTML parser unit tests so that
tests can run without a physical device. Fixture coverage does not establish
hardware or firmware compatibility; validation of the current apply path on
real hardware is still pending.

## Files

| File | Source Page |
|------|-------------|
| `port_settings.html` | Port Settings page |
| `port_stats.html` | Port operational status and statistics page |
| `vlan_static.html` | Static VLAN configuration |
| `vlan_port_based.html` | Port-based VLAN configuration |
| `trunk_group.html` | Trunk Group configuration |
| `trunk_lacp.html` | LACP status page |
| `device_info.html` | System / Device Information page |

## Capturing Fixtures

1. Log in to the switch web interface in a browser.
2. Navigate to the target page.
3. Use browser "Save page as" → **Webpage, HTML only**.
4. Place the saved file in this directory.
5. Sanitise any credentials or sensitive IP addresses before committing.

## Malformed VLAN fixtures

The `malformed_vlan_*.html` files are synthetic invalid responses for VLAN ID,
access VLAN, native VLAN, permit list, and mode parsing regression tests. They
must be rejected rather than converted to missing or empty configuration.

## Management-plane source fixtures

`management_ip.html`, `user_account.html`, `system_management.html`, and
`management_form_helpers.js` originate from authenticated live GETs on firmware
V100SP11240725 (2026-09-17). Network addresses were replaced with RFC 5737
fixture addresses; no MAC, serial, cookie, session ID, or password value is
included. User fields were blank on the device. The IP/user form structure and
JavaScript are preserved. System and shared helper fixtures contain only the
relevant extracted functions, omitting unrelated device controls/assets.

These fixtures prove UI field names and serialization, not successful network
or password mutation. Save configuration was independently confirmed by live
POST with `{"code":0,"data":""}`. Reboot and IP/password mutations remain
untested at this discovery stage. See the management discovery report for
confidence levels and observed UI constraints.
