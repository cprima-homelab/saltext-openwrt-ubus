"""
Collect configured-state and runtime evidence from a live OpenWrt device
and persist the records as JSON files.

Reads connection details from environment (or .env):

    LIVE_HOST                  required  IP or hostname or FQDN
    LIVE_PORT                  optional  port (default 443)
    LIVE_SCHEME                optional  "https" or "http" (default "https")
    LIVE_VERIFY_SSL            optional  "true" to verify TLS cert (default "false")
                                         set to "true" for Caddy/ACME targets with valid certs
    LIVE_SALT_AGENT_PASSWORD   required  salt-agent rpcd password
    LIVE_DEVICE_SLUG           optional  directory name under EVIDENCE_OUTPUT_DIR
                                         (default: LIVE_HOST)
    EVIDENCE_OUTPUT_DIR        required  root directory for output files
                                         e.g. T:/netops

Output layout::

    <EVIDENCE_OUTPUT_DIR>/
    └── <slug>/
        └── <ISO-timestamp>/
            ├── configured__network.json
            ├── configured__dhcp.json
            ├── configured__wireless.json
            ├── configured__firewall.json
            ├── configured__system.json
            ├── configured__dropbear.json
            ├── runtime__network.json
            ├── runtime__system.json
            └── runtime__services.json

Usage::

    uv run python tools/collect_evidence.py
"""

import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LIVE_HOST = os.environ.get("LIVE_HOST", "")
LIVE_PORT = int(os.environ.get("LIVE_PORT", "443"))
LIVE_SCHEME = os.environ.get("LIVE_SCHEME", "https")
LIVE_VERIFY_SSL = os.environ.get("LIVE_VERIFY_SSL", "false").lower() == "true"
LIVE_SALT_AGENT_PASSWORD = os.environ.get("LIVE_SALT_AGENT_PASSWORD", "")
LIVE_DEVICE_SLUG = os.environ.get("LIVE_DEVICE_SLUG", "") or LIVE_HOST
EVIDENCE_OUTPUT_DIR = os.environ.get("EVIDENCE_OUTPUT_DIR", "")

MIGRATION_PACKAGES = ["network", "dhcp", "wireless", "firewall", "system", "dropbear"]
RUNTIME_DOMAINS = ["network", "system", "services"]


def _require(name, value):
    if not value:
        print(f"ERROR: {name} is not set.", file=sys.stderr)
        sys.exit(1)


def _make_rpc_client():
    from saltext.uci_ubus._internal.rpc import UbusRpcClient

    client = UbusRpcClient(
        host=LIVE_HOST,
        username="salt-agent",
        password=LIVE_SALT_AGENT_PASSWORD,
        port=LIVE_PORT,
        scheme=LIVE_SCHEME,
        verify_ssl=LIVE_VERIFY_SSL,
        timeout=10,
    )
    client.login()
    return client


def _wire_module(client):
    from saltext.uci_ubus.modules import ubus_jsonrpc as mod

    mod.__opts__ = {"proxy": {"proxytype": "uci_ubus_jsonrpc"}, "id": LIVE_DEVICE_SLUG}
    mod.__proxy__ = {"uci_ubus_jsonrpc.call": client.call}
    return mod


def main():
    _require("LIVE_HOST", LIVE_HOST)
    _require("LIVE_SALT_AGENT_PASSWORD", LIVE_SALT_AGENT_PASSWORD)
    _require("EVIDENCE_OUTPUT_DIR", EVIDENCE_OUTPUT_DIR)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out_dir = Path(EVIDENCE_OUTPUT_DIR) / LIVE_DEVICE_SLUG / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {LIVE_HOST}:{LIVE_PORT} as salt-agent ...")
    client = _make_rpc_client()
    mod = _wire_module(client)

    available = mod.configs()

    errors = []

    for pkg in MIGRATION_PACKAGES:
        if pkg not in available:
            print(f"  skip configured__{pkg} (package not present)")
            continue
        try:
            record = mod.config_evidence(pkg)
            path = out_dir / f"configured__{pkg}.json"
            path.write_text(json.dumps(record, indent=2))
            print(f"  wrote {path.name}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"  ERROR configured__{pkg}: {exc}", file=sys.stderr)
            errors.append(f"configured__{pkg}: {exc}")

    for domain in RUNTIME_DOMAINS:
        try:
            record = mod.runtime_evidence(domain)
            path = out_dir / f"runtime__{domain}.json"
            path.write_text(json.dumps(record, indent=2))
            print(f"  wrote {path.name}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"  ERROR runtime__{domain}: {exc}", file=sys.stderr)
            errors.append(f"runtime__{domain}: {exc}")

    print(f"\nOutput: {out_dir}")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
