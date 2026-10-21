---
name: unifi-readonly-audit
description: >
  Run a read-only security and configuration audit of a UniFi gateway through
  the mcp-unifi MCP server. Use whenever the user asks for a UniFi audit,
  firewall review, WLAN or VLAN review, firmware check, open-port check,
  threat-management or DNS review, or a read-only pass against a site this
  server manages, including when they do not say "audit". Only call tools
  listed under call in the tool registry below. Never call a mutating tool.
  Never invent a tool name for a surface this server does not implement.
---

# UniFi read-only audit

Audit one UniFi site through an already-connected mcp-unifi server. The deployment this skill expects is `deploy/compose/`: one container, `MCP_UNIFI_READONLY` hardcoded on, HTTP bound to that host's Tailscale address, or the stdio compose file. You do not start that container, you do not pin a certificate, and you do not change a gateway.

Remediation in the report is a sentence a person can do in the UniFi UI. It is not a tool call.

## Before any check

1. Use the MCP connection the user already configured. HTTP clients send `Authorization: Bearer` with the bearer token. You do not print that token, an API key, or a passphrase. `[REDACTED]` stays redacted.
2. Call `tools/list`. If any name under `do_not_call` in the registry below is listed, stop. The server is not in read-only mode. The report is that fact and nothing else. Do not call the tool.
3. Pass `controller` on every call. Use the controller `name` from the deployment's controllers file (`home` or `cabin` in the example). Do not rely on a default when more than one controller is configured.
4. Only call names under `call`. Names under `not_this_check` are real tools and the wrong tool for this audit. Names under `do_not_call` are every mutating tool registered in this repo, including ones whose names do not look like writes: `confirm_destructive_action`, `restore_config`, `block_client`, `unblock_client`, `quarantine_client`, `reconnect_client`, `restart_device`, `rename_device`, `locate_device`, `toggle_traffic_rule`, `toggle_traffic_route`, `trigger_speedtest`.
5. A payload that contains an `error` key is a failed read. Record that check as `gap` with the error text and continue with the other checks.
6. If any payload contains `"stub_mode": true`, the report is a stub dry run. Say so in the header. Use severity `info` or `gap` only.

`hide_ssid` is not a security control. Do not file a finding because an SSID is broadcast.

## Checks

Work in this order. Record the tool name and the fields you actually used next to every finding.

### Firmware

- `get_system_info`. Read `version`, `previous_version`, `update_available`, `udm_version`, `console_display_version`, `build`, `uptime`. `update_available: true` is **medium**. A version string with no `update_available` flag is **info** (you cannot see currency). Do not invent a CVE from a version number.
- `list_devices`. Each record includes `version` plus `name`, `model`, `type`, `mac`, `state`. Keep those fields for the report and drop the rest of the record (full records are large). Device `version` values that differ across the same model family are **low** unless `get_system_info` says an update is available, in which case cite both and keep **medium**.
- If `list_devices` is truncated, call `get_device_stats` per remaining MAC. That shaper returns `version` even though the tool's summary list does not name it. Do not loop `get_device_stats` when `list_devices` already returned `version`.
- `get_console_health` for `network_app_version` and `state`. A state other than `healthy` is **medium** (or **high** when `state` is `console_unreachable` or `credentials_invalid` and you could not read the site at all). It is not a firmware finding.
- `get_console_firmware` only as an extra. It needs a console username and password, which this deployment does not mount. The response shape is an unverified passthrough. On error, record UniFi OS firmware as `gap`. Do not treat the error as "no update".

### Zone firewall, legacy rules, port forwards

- `list_firewall_zones`. Fields: `_id`, `name`, `zone_key`, `default_zone`, `network_ids`. An empty list means the site is not on the zone-based firewall, or the read failed. Empty is not "no firewall".
- `list_firewall_policies`. Fields: `_id`, `name`, `action` (`ALLOW`, `BLOCK`, `REJECT`), `enabled`, `predefined`, `index`, `protocol`, `source`, `destination`. `source.zone_id` and `destination.zone_id` match `list_firewall_zones`. Report `index` as the order the controller returned. You cannot reorder. See API gaps.
- `list_firewall_rules`. Legacy rulesets such as `WAN_IN` and `LAN_IN`. Fields: `_id`, `name`, `ruleset`, `rule_index`, `action`, `enabled`, `protocol`, and the `src_*` / `dst_*` fields. A zone-based site returns `[]` here even when the firewall is configured. Use the policies for that site.
- `audit_open_ports` is the WAN exposure summary. Use its classification rather than re-deriving it. It returns `port_forwards`, `wan_accept_rules`, `wan_accept_policies`, `firewall_model` (`legacy`, `zone-based`, `mixed`, `none`), `wan_zone_resolved`, `return_traffic_policies_excluded`, `port_forward_mirror_policies`. A policy with `duplicates_port_forward: true` is the same exposure as the port forward it mirrors. Count it once. If `wan_zone_resolved` is false, the WAN policy half is `gap`, not a pass.
- `list_port_forwards` for the forward records themselves: `_id`, `name`, `enabled`, `proto`, `src`, `fwd`, `fwd_port`, `dst_port`. An enabled forward is **high**. A forward whose destination port is a management port (22, 80, 443, 8443, or the UniFi controller port) is **critical**.
- An enabled `ALLOW` policy from the WAN / External zone to a broad internal zone with no port restriction is **critical**. The same shape with a single documented port is **high**. `audit_open_ports` already excludes return-traffic (`RESPOND_ONLY`) policies. Do not file those.
- An enabled legacy `WAN_*` `accept` rule that is not the established/related boilerplate is **high**.
- `list_firewall_groups` and, when a rule cites a group id you need to interpret, `get_firewall_group_details`. Do not call the detail tool for every group.

Disabled rules and policies are **info**, cited so the report shows you saw them.

### WLAN

`list_wlans` returns one record per SSID. Use `enabled`, `security`, `wpa_mode`, `is_guest`, `networkconf_id`, `name`. The passphrase is `[REDACTED]` on purpose.

| What you see | Severity |
|---|---|
| `enabled` and `security` `open` | **high** (critical if the SSID is not a guest network) |
| `enabled` and `wpa_mode` other than `wpa2` or `wpa3`, including empty | **high** |
| `enabled` and `wpa_mode` `wpa2` | **info**. Note that WPA3 is not on. Do not raise this on its own. |
| `enabled` and `wpa_mode` `wpa3` | **info** |
| `security` `wpaeap` | **info** for the mode. RADIUS profiles are an API gap. Say you could not read the profile. |
| `is_guest: false` on an SSID whose network `purpose` is `guest`, or whose name is the guest network | **high** |
| `is_guest: true` | **info** (client isolation is on for that SSID) |

Protected Management Frames are not a field `list_wlans` documents. If the record contains `pmf_mode`, report that value: `required` is **info**, `optional` is **low**, `disabled` on a `wpa2` or `wpa3` SSID is **medium**. If the key is absent, PMF is **gap**. Do not infer it from `wpa_mode`.

`is_guest: true` is this server's client-isolation flag. There is no separate guest-isolation tool.

`list_ap_groups` is optional context for which APs carry an SSID (`device_macs`). It is not a security finding by itself.

`get_guest_portal` is the site-wide captive portal, not a WLAN field. Read `portal_enabled`, `auth`, `expire`, `restricted_subnet_1`, `restricted_subnet_2`, `restricted_subnet_3`, `voucher_enabled`. `portal_enabled: true` with `auth` `none` on a network you are treating as isolated is **medium** (click-through, no credential). `voucher_enabled` is a boolean on this setting. It is not a voucher list. See API gaps.

### VLAN and segmentation

- `list_networks`. Use `_id`, `name`, `purpose`, `vlan`, `vlan_enabled`, `ip_subnet`, `dhcpd_enabled`, `enabled`. `purpose` `wan` is the uplink, not a LAN. VPN key material on these records is redacted. Do not try to recover it.
- `get_network_details` for each enabled non-WAN network. Use the `network`, `dhcp`, and `ipv6` sections. The `raw` object may contain `network_isolation_enabled`. If that key is present, `false` on a network whose purpose is `guest` or whose name is an IoT or guest network is **high**. If the key is absent, network isolation is **gap** for that network. Do not store a guessed `false`.
- Join `list_firewall_zones` `network_ids` to network `_id` so each LAN has a zone. Two corporate LANs in the same zone with an enabled `ALLOW` policy for that zone pair and no address restriction is **medium**. A guest or IoT subnet with no `BLOCK` policy toward the main LAN subnet, and no `network_isolation_enabled: true`, is **high**.
- `list_routes` and `get_route_details` when a route's destination is a subnet you called isolated. A static route that forwards into that subnet is **high**. Cite the route name and destination.
- `list_port_profiles` is optional. Use it only when a switch port's VLAN membership is part of the question the user asked. Do not invent a LAG finding from a port profile. LAG is an API gap.

`list_firewall_rules` on a legacy site: an enabled `LAN_IN` accept from a guest or IoT subnet to the main LAN is **high** when no earlier deny covers that pair. Cite `rule_index`. You cannot reorder. See API gaps.

### Admin accounts and 2FA

No registered tool lists UniFi OS administrators or their 2FA enrollment. Record both as **gap**. Do not score them as pass.

`get_console_info` can return `remote_access_enabled`, `sso_enabled`, and `cloud_connected` when the console answers the Network API key. Report those values as **info**, or **medium** when `remote_access_enabled` is true. A 401 or a not-configured error means those fields are **gap**. It does not mean remote access is off. The same call does not report 2FA.

`list_access_users` is UniFi Access people, not console administrators. Do not call it for this check.

### UPnP

No registered tool reads UPnP. Record UPnP as **gap**. Do not infer it from an empty firewall list, a port forward, or a missing key.

### DNS and threat management

- `get_threat_management`. Use `enabled`, `mode` (`off`, `ids`, `ips`), `enabled_signature_categories`, `enabled_networks`, `endpoint_scanning`, `ad_blocking_enabled`, `dns_filtering`, `honeypot_enabled`. `mode` `off` (or `enabled` false) is **medium**. `dns_filtering` false is **low**. `ad_blocking_enabled` false is **info**.
- `list_content_filters` and, for each enabled profile, `get_content_filter_details`. Fields: `name`, `enabled`, `categories`, `allow_list`, `block_list`, `network_ids`, `client_macs`, `safe_search`, `schedule`. No profiles, and `dns_filtering` false, is one **low** finding, not two. Content filters are not DNS policies. See API gaps.
- `list_honeypots` when `honeypot_enabled` is true, so the report names the networks. An empty list with `honeypot_enabled` true is **low**.
- DHCP DNS servers, if present, are under the `dhcp` section of `get_network_details` (`dhcpd_*` keys). Report them as **info**. Do not call them DNS policy.

`get_wan_status` and `get_wan_ipv6` are reads of WAN state and WAN IPv6. Use them as **info** context (is the uplink up, is IPv6 on). They are not WAN configuration CRUD. See API gaps.

`get_teleport_config` is the only VPN read. It returns `enabled`, `vpn_networks`, and `clients_via_local_api` (always false: there is no client roster). `enabled: true` is **info** plus a note that clients and site-to-site tunnels are not readable. See API gaps.

## API gaps

These surfaces have no tool, or only the read named above. Do not attempt them. Do not call a mutating tool "to look". Do not invent a name.

| Surface | What you may cite | Do not attempt |
|---|---|---|
| Policy ordering | `index` on `list_firewall_policies`, `rule_index` on `list_firewall_rules` | Reorder, move, or insert at a position. Zone policy writes exist in the server and are hidden in read-only mode. They are not an ordering tool. |
| Zone CRUD | `list_firewall_zones` | Create, update, or delete a zone. |
| Traffic-matching lists | Nothing. `list_traffic_rules`, `get_traffic_rule_details`, `list_traffic_routes`, and `get_traffic_route_details` are traffic rules and routes, not traffic-matching lists. Do not call them as a substitute. | Any traffic-matching-list action. |
| ACL | Nothing | Any ACL read or write. |
| DNS policies | `dns_filtering` on `get_threat_management`, and content-filter profiles | DNS policy CRUD. Content filters are a different object. |
| LAG | Nothing | Any link-aggregation read or write. `list_port_profiles` is not LAG. |
| VPN | `get_teleport_config` only (listener on/off, no clients) | Site-to-site tunnels, VPN servers, client roster, invitations. |
| WAN | `get_wan_status`, `get_wan_ipv6` | WAN profile create/update/delete. `set_wan_ipv6` is a write and is under `do_not_call`. |
| RADIUS | A redacted secret if one appears on a network record. `security: wpaeap` on a WLAN. | RADIUS profile list or edit. |
| Tags | Nothing | Device-tag list or edit. |
| Vouchers | `voucher_enabled` on `get_guest_portal` | Voucher create, list, or revoke. |

`not_this_check` names real read tools that are easy to misuse for the rows above. Do not call them during this audit.

## Severity

| Severity | Use it when |
|---|---|
| critical | WAN allow-all into the internal zone, or an enabled port forward to a management port |
| high | Other enabled WAN exposure, open or non-WPA2/WPA3 SSID, guest SSID without client isolation, guest/IoT subnet with no isolation control you could read |
| medium | Update available, threat management off, captive portal with `auth` `none`, PMF disabled when the field is present, remote access enabled |
| low | WPA2-only is not this. DNS filtering off, honeypot flag inconsistent, PMF optional |
| info | Checked, and the value is not one of the rows above. Also every stub-mode result. |
| gap | No tool, the field was absent, or the read returned `error`. A gap is not a pass. |

Count `gap` separately from passes. The summary line is `critical / high / medium / low / info / gap`.

## Report

Write this template. Fill every section. A section with no row still says `none` or lists the gap. Do not drop a section because the site looked fine.

```markdown
# UniFi read-only audit

- Controller:
- Collected at:
- Read-only server: yes | no (stop if no)
- Stub data: yes | no
- Summary: critical= high= medium= low= info= gap=

## Findings

| ID | Area | Severity | Evidence | Tool |
|----|------|----------|----------|------|
| F1 | | | | |

## Firmware

## Firewall and exposure

## WLAN

## Segmentation

## Admins and 2FA

## UPnP

## DNS and threat management

## Not assessed

| Surface | Why |
|---------|-----|
| Policy ordering | Read `index` only. No reorder tool. |
| Zone CRUD | List only. |
| Traffic-matching lists | No tool. |
| ACL | No tool. |
| DNS policies | No tool. Content filters and `dns_filtering` are a different object. |
| LAG | No tool. |
| VPN | Teleport listener only, when `get_teleport_config` was called. |
| WAN | Status and IPv6 read only. |
| RADIUS | No profile tool. |
| Tags | No tool. |
| Vouchers | `voucher_enabled` only. |

## Operator notes

Remediation belongs in the UniFi UI. This audit does not apply it.
```

## Tool registry

The lists are the contract. `do_not_call` is every mutating tool registered in this repository. A test fails if that set drifts.

<!-- tool-registry:start -->

```yaml
call:
  - audit_open_ports
  - get_console_firmware
  - get_console_health
  - get_console_info
  - get_content_filter_details
  - get_device_stats
  - get_firewall_group_details
  - get_guest_portal
  - get_network_details
  - get_route_details
  - get_system_info
  - get_teleport_config
  - get_threat_management
  - get_wan_ipv6
  - get_wan_status
  - list_ap_groups
  - list_content_filters
  - list_devices
  - list_firewall_groups
  - list_firewall_policies
  - list_firewall_rules
  - list_firewall_zones
  - list_honeypots
  - list_networks
  - list_port_forwards
  - list_port_profiles
  - list_routes
  - list_wlans
not_this_check:
  - get_traffic_route_details
  - get_traffic_rule_details
  - list_access_users
  - list_traffic_routes
  - list_traffic_rules
do_not_call:
  - block_client
  - confirm_destructive_action
  - create_dynamic_dns
  - create_firewall_group
  - create_firewall_policy
  - create_firewall_rule
  - create_guest_network
  - create_honeypot
  - create_iot_network
  - create_port_forward
  - create_port_profile
  - create_route
  - create_static_dhcp_lease
  - create_traffic_rule
  - create_vlan
  - create_wlan
  - delete_content_filter
  - delete_dynamic_dns
  - delete_firewall_group
  - delete_firewall_policy
  - delete_firewall_rule
  - delete_honeypot
  - delete_port_forward
  - delete_port_profile
  - delete_route
  - delete_static_dhcp_lease
  - delete_vlan
  - delete_wlan
  - locate_device
  - provision_camera
  - provision_homelab_service
  - quarantine_client
  - reconnect_client
  - rename_device
  - restart_device
  - restore_config
  - set_camera_privacy_mode
  - set_camera_recording_mode
  - set_guest_portal
  - set_lan_ipv6
  - set_motion_sensitivity
  - set_port_state
  - set_radio_channel
  - set_radio_min_rssi
  - set_radio_tx_power
  - set_teleport_enabled
  - set_threat_management
  - set_wan_ipv6
  - toggle_traffic_route
  - toggle_traffic_rule
  - trigger_speedtest
  - unblock_client
  - update_content_filter
  - update_dynamic_dns
  - update_firewall_group
  - update_firewall_policy
  - update_firewall_rule
  - update_port_forward
  - update_port_profile
  - update_route
  - update_static_dhcp_lease
  - update_traffic_route
  - update_traffic_rule
  - update_vlan
  - update_wlan
```

<!-- tool-registry:end -->
