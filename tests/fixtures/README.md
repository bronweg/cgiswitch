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
