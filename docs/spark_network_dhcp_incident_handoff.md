# DGX Spark DHCP / VLAN Incident Handoff

Date: 2026-08-05
Status: investigation packet for Networking
Audience: networking agent with authorized, read-only access to pfSense, managed switches, and DHCP logs
Priority: high - a production Spark management NIC received an unintended DHCP lease

## Executive Brief

Both DGX Spark workers were reported unavailable. The current state is healthy, but the incident exposed a real network configuration problem on `spark-8cea`.

Between 2026-07-27 and the restart on 2026-08-05, its physical management NIC was assigned `172.16.1.73`, rather than its intended `192.168.2.151` management address. After the restart, the same NIC correctly received `192.168.2.151` from the expected `192.168.2.1` DHCP server.

The root cause is not yet proven. A `172.16.1.73` DHCP lease on the physical NIC means a DHCP responder for that scope was reachable on its wired Layer-2 broadcast domain, or that a DHCP relay/VLAN assignment was wrong. The Spark did not independently join an external network.

Do not change worker network configuration until the DHCP/VLAN source has been identified and there is a rollback path.

## Current State

Both workers are healthy as of this handoff:

| Worker | Management MAC | Expected address | Current service state |
| --- | --- | --- | --- |
| `spark-bb49` | `4c:bb:47:2a:bb:49` | `192.168.2.150` | SSH reachable; `ollama` and `norllama-gateway` active; `http://192.168.2.150:18151/v1/models` returns HTTP 200 |
| `spark-8cea` | `4c:bb:47:2a:8c:ea` | `192.168.2.151` | SSH reachable; `ollama` and `norllama-gateway` active; `http://192.168.2.151:18151/v1/models` returns HTTP 200 |

Both workers advertise `qwen3-coder:30b-a3b-q4_K_M`. The Norllama front door at `https://llm.home.arpa/v1/models` also advertises that model.

## Confirmed Evidence

### `spark-8cea` received the wrong DHCP scope

NetworkManager identifies the physical management interface as `enP7s7`, using connection `Wired connection 2` with `ipv4.method=auto`.

From the first observed lease on July 27 through the restart on August 5, this interface repeatedly received the `172.16.1.73` DHCP lease:

```text
2026-07-27T12:46:57-05:00 ... dhcp4 (enP7s7): state changed new lease, address=172.16.1.73
2026-08-05T07:16:53-05:00 ... dhcp4 (enP7s7): state changed new lease, address=172.16.1.73
```

The journal contains 422 renewals of this lease, approximately every 30 minutes. This was not a stale address retained from one failed connection attempt.

After the restart, the worker obtained the intended configuration:

```text
192.168.2.151/24
default via 192.168.2.1
dhcp_server_identifier = 192.168.2.1
```

### This was not a Docker address conflict

Docker uses `172.17.0.1/16` on `docker0`. The problematic `172.16.1.73` address was assigned directly to `enP7s7`, the physical management NIC.

### This was not a GPU, Ollama, or kernel crash

Before the user restart, Ollama served a local API request successfully at `06:51:54 CDT`. There is no retained evidence of OOM termination, NVIDIA Xid/GPU failure, kernel panic, watchdog reset, or thermal shutdown.

### `spark-bb49` shutdown was clean, but its initiator is unknown

`spark-bb49` ended its previous boot with a clean shutdown on August 4 at `17:10 UTC` (`12:10 CDT`). DS4 logged shutdown draining and there is no retained hardware or model-runtime crash evidence. The exact command or actor that initiated shutdown is not available in retained logs.

Its clock was wrong during boot, which makes historical journal timestamps confusing. NTP and RTC are currently synchronized.

## Networking Interpretation

The relevant event is a DHCP assignment on a physical wired NIC. The likely fault classes are:

1. The `spark-8cea` switch port had an incorrect VLAN or untagged VLAN membership.
2. A second or rogue DHCP responder was present on that Layer-2 broadcast domain.
3. pfSense DHCP or a DHCP relay was serving the wrong scope to the Spark's VLAN.

This incident does not prove that the Spark joined another network by itself. DHCP response requires a network path to the responding service.

The exact DHCP server that issued `172.16.1.73` is not preserved in the retained NetworkManager journal entries, so firewall, switch, and DHCP evidence are required to establish the source.

## Investigation Objectives

1. Identify the DHCP server, relay, and VLAN that issued `172.16.1.73` to `4c:bb:47:2a:8c:ea`.
2. Determine why only `spark-8cea` was affected while its peer remained on the expected management subnet.
3. Confirm the intended stable DHCP reservation and port/VLAN configuration for both Spark management NICs.
4. Remove the unintended DHCP source or VLAN leak, with an explicit rollback plan.
5. Prove that normal lease renewal keeps both workers on their expected addresses and able to serve Norllama.

## Required Read-Only Checks

Use brokered Norman Keys access for `networking/firewall` and the appropriate managed-switch logical credential. Do not read repo-local plaintext credential files. If Norman Keys is unavailable, report the credentialed action blocked with the required logical alias; TUI agents do not invoke `cred` or request a vault passphrase.

### pfSense / DHCP

Inspect leases, historical DHCP logs, and relevant interface/relay configuration for:

- MAC: `4c:bb:47:2a:8c:ea`
- Hostname: `spark-8cea`
- Unexpected address: `172.16.1.73`
- Expected address: `192.168.2.151`
- Incident window: 2026-07-27 12:46 CDT through 2026-08-05 07:16 CDT

Establish:

- Which service owns `172.16.1.0/24`.
- Whether pfSense ever issued or relayed `172.16.1.73` to that MAC.
- The DHCP server identifier, gateway, and option set associated with that scope.
- Whether any relay forwarded Spark-VLAN broadcasts to the `172.16.1.0/24` scope.
- Whether the expected `192.168.2.0/24` scope has reservations for both Spark MAC addresses.

Expected reservations:

| MAC | Reserved address |
| --- | --- |
| `4c:bb:47:2a:bb:49` | `192.168.2.150` |
| `4c:bb:47:2a:8c:ea` | `192.168.2.151` |

### Managed switch

Locate the physical switch ports carrying the management NICs for both workers. Inspect their current and historical configuration:

- Access/untagged VLAN
- Tagged VLAN membership
- Native VLAN
- Port profile/template
- MAC address table observations for both MACs
- Any recent port, VLAN, trunk, or profile changes
- Whether the affected port could receive broadcasts from the `172.16.1.0/24` VLAN

Compare `spark-8cea` directly with the working `spark-bb49` port. The difference is likely more informative than an estate-wide review.

### DHCP discovery and containment evidence

Determine whether another DHCP responder existed on the Spark Layer-2 domain:

- Review DHCP snooping, alert, or packet-capture history if available.
- Review ARP, MAC, and interface evidence for a server or relay on `172.16.1.0/24`.
- Determine whether a lab, guest, transit, VPN, or management VLAN has leaked onto the Spark port.

Do not trust a current clean state as proof that the historical configuration was correct. The restart may have coincided with a switch/VLAN state change or removal of the unintended responder.

## Change Gate

Do not make these changes before identifying the fault source:

- Set a static address in NetworkManager as a workaround.
- Move the Spark to a new VLAN.
- Disable broad DHCP services or relays.
- Reconfigure normal TUI traffic to direct worker URLs.

Prefer verified DHCP reservations plus correct Layer-2 segmentation over manual worker addressing, unless the network investigation proves reservations cannot provide a reliable result.

Any corrective change must include:

1. Exact target device and configuration diff.
2. Rollback procedure and out-of-band management path.
3. Expected DHCP lease/server identifier after the change.
4. A controlled lease-renewal verification.

## Verification After Remediation

After a source and remediation are confirmed:

1. Verify both management NICs are on the intended VLAN and DHCP scope.
2. Confirm the reservations shown above are active.
3. Renew the lease on one worker at a time, with an established rollback/recovery path.
4. Confirm:

```text
spark-bb49: 192.168.2.150/24, default via 192.168.2.1
spark-8cea: 192.168.2.151/24, default via 192.168.2.1
```

5. Verify both are SSH reachable and return HTTP 200:

```bash
curl -fsS http://192.168.2.150:18151/v1/models
curl -fsS http://192.168.2.151:18151/v1/models
curl -fsS https://llm.home.arpa/v1/models
```

6. Recheck after at least one normal DHCP renewal interval. The historical bad lease renewed roughly every 30 minutes.

## Non-Network Alert Context

The overwhelming infrastructure/TUI warning observed around this incident was a stale scheduled TUI route-proof failure at `07:15`. It reported four web-session prompt timeouts. It is not direct evidence of GPU failure or of the DHCP issue.

Do not rerun `norman-tui-route-proof.service` as part of this investigation. It sends live prompts and can permit cloud final authorities after local preflight. The user does not want Bedrock or other paid-cloud fallback for this work.

## Deliverable

Return a short incident report containing:

1. Confirmed root cause, or the remaining evidence gap if it cannot be proven.
2. DHCP server/relay identity for `172.16.1.73`.
3. Exact affected switch port and VLAN configuration, with comparison to `spark-bb49`.
4. Remediation performed or proposed, including rollback.
5. Lease-renewal and service verification results for both workers.
6. Any recommendation for persistent DHCP monitoring, rogue-DHCP detection, or configuration drift alerts.
