# Security Policy

## Supported Versions

Only the latest release is actively maintained.

## What Is NOT a Security Issue

This addon is a **local Modbus TCP server** designed to run on your home network.
The following are intentional design decisions, not vulnerabilities:

- The Modbus server accepts connections from any LAN client on port 502 — this is
  required for Tibber Bridge to connect, and is expected behavior for a local Modbus server.
- The addon reads HA sensor states via the Supervisor API — this is the standard
  HAOS addon mechanism and requires the `homeassistant_api: true` flag.
- No authentication is implemented on the Modbus layer — Modbus TCP has no
  authentication by design, and this server only exposes read-only PV data.

## What IS a Security Issue

Please report privately if you find:

- A way to exfiltrate `SUPERVISOR_TOKEN` or other secrets from the addon
- Remote code execution via malformed Modbus packets
- A way to cause the addon to make external network requests beyond the local
  Supervisor API (`http://supervisor/`)
- Any path traversal or file inclusion vulnerabilities in log or register file handling

## Reporting

Please report security vulnerabilities privately via
[GitHub Security Advisories](https://github.com/Chillout222/ha-fake-solis-probe/security/advisories/new)
rather than opening a public issue.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will respond within 7 days.
