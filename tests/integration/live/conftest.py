"""
Fixtures for saltext-uci integration tests against a live OpenWrt device.

Prerequisites on the target device:
    - salt-agent system user and rpcd login provisioned (salt-agent-ubus postinst)
    - /usr/share/rpcd/acl.d/salt-agent-ubus.json deployed
    - rpcd and uhttpd-mod-ubus running

Configuration via environment variables (loaded from .env):

    LIVE_HOST                 required  IP or hostname of the target device
    LIVE_PORT                 optional  HTTP port (default: 80)
    LIVE_SALT_AGENT_PASSWORD  required  password for the salt-agent rpcd login
    LIVE_ROOT_PASSWORD        optional  root SSH password; SSH-dependent tests
                                        are skipped when absent
    LIVE_SSH_PORT             optional  SSH port (default: 22)

All tests in this suite are read-only — no UCI mutations are issued.
"""

import os
import socket

import paramiko
import pytest
from dotenv import load_dotenv

load_dotenv()

LIVE_HOST = os.environ.get("LIVE_HOST", "")
LIVE_PORT = int(os.environ.get("LIVE_PORT", "80"))
LIVE_UBUS_URL = f"http://{LIVE_HOST}:{LIVE_PORT}/ubus"
LIVE_SALT_AGENT_PASSWORD = os.environ.get("LIVE_SALT_AGENT_PASSWORD", "")
LIVE_ROOT_PASSWORD = os.environ.get("LIVE_ROOT_PASSWORD", "")
LIVE_SSH_PORT = int(os.environ.get("LIVE_SSH_PORT", "22"))


def _device_reachable() -> bool:
    if not LIVE_HOST:
        return False
    try:
        with socket.create_connection((LIVE_HOST, LIVE_PORT), timeout=3):
            return True
    except OSError:
        return False


def make_rpc_client():
    """Return an authenticated UbusRpcClient for the live device.

    UbusRpcClient builds https:// by default; LAN devices without a cert
    serve plain HTTP, so we override the URL after construction.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.openwrt_ubus.utils.rpc import UbusRpcClient

    client = UbusRpcClient(
        host=LIVE_HOST,
        username="salt-agent",
        password=LIVE_SALT_AGENT_PASSWORD,
        port=LIVE_PORT,
        verify_ssl=False,
        timeout=10,
    )
    client.url = LIVE_UBUS_URL
    client.login()
    return client


@pytest.fixture(scope="session")
def live_device():
    """Session fixture — skips the entire suite when the device is not reachable
    or LIVE_SALT_AGENT_PASSWORD is not set."""
    if not LIVE_HOST:
        pytest.skip("LIVE_HOST is not set.")
    if not LIVE_SALT_AGENT_PASSWORD:
        pytest.skip("LIVE_SALT_AGENT_PASSWORD is not set.")
    if not _device_reachable():
        pytest.skip(
            f"Live device ({LIVE_HOST}:{LIVE_PORT}) is not reachable. "
            "Check network connectivity."
        )
    yield LIVE_HOST


@pytest.fixture(scope="session")
def ubus_client(live_device):  # pylint: disable=unused-argument
    """Authenticated UbusRpcClient for the duration of the test session."""
    yield make_rpc_client()


@pytest.fixture(scope="module")
def uci_module(live_device):  # pylint: disable=unused-argument
    """Salt execution module wired to the live device.

    Injects the production ubus_jsonrpc → ubus_ops code path without
    requiring a running Salt master or proxy minion.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.openwrt_ubus.modules import ubus_jsonrpc as mod

    client = make_rpc_client()
    mod.__opts__ = {"proxy": {"proxytype": "openwrt_ubus_jsonrpc"}, "id": LIVE_HOST}
    mod.__proxy__ = {"openwrt_ubus_jsonrpc.call": client.call}
    yield mod


@pytest.fixture(scope="session")
def ssh_client(live_device):  # pylint: disable=unused-argument
    """Paramiko SSH session as root — used for file-level read checks.

    Skipped when LIVE_ROOT_PASSWORD is not set; only SSH-dependent tests
    declare this fixture as a parameter.
    """
    if not LIVE_ROOT_PASSWORD:
        pytest.skip("LIVE_ROOT_PASSWORD is not set — skipping SSH-dependent tests.")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
    client.connect(
        LIVE_HOST,
        port=LIVE_SSH_PORT,
        username="root",
        password=LIVE_ROOT_PASSWORD,
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )
    yield client
    client.close()


def read_device_config(ssh_client, config: str) -> str:
    """Read /etc/config/<config> from the live device via SSH."""
    _, stdout, _ = ssh_client.exec_command(f"cat /etc/config/{config}")
    return stdout.read().decode()
