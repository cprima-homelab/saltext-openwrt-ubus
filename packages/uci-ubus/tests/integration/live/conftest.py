"""
Fixtures for saltext-uci integration tests against up to 3 live OpenWrt devices.

Prerequisites on each target device:
    - salt-agent system user and rpcd login provisioned (salt-agent-ubus postinst)
    - /usr/share/rpcd/acl.d/salt-agent-ubus.json deployed
    - rpcd and uhttpd-mod-ubus running

Configuration via environment variables (loaded from .env). Devices are
addressed by generic slot number, not codename, since the physical device
behind a slot can change over time. Slots without a HOST are simply absent
(not an error) — the whole suite skips cleanly when no slot is configured.

    LIVE_DEVICE_<N>_HOST                 required  IP or hostname (N = 1..3)
    LIVE_DEVICE_<N>_PORT                  optional  HTTP port (default: 80)
    LIVE_DEVICE_<N>_SALT_AGENT_PASSWORD   required  password for the salt-agent rpcd login
    LIVE_DEVICE_<N>_ROOT_PASSWORD         optional  root SSH password; SSH-dependent
                                                     tests are skipped when absent
    LIVE_DEVICE_<N>_SSH_PORT              optional  SSH port (default: 22)

All tests in this suite are read-only — no UCI mutations are issued.
"""

import os
import socket

import paramiko
import pytest
from dotenv import load_dotenv

load_dotenv()

MAX_DEVICE_SLOTS = 3


def _configured_devices():
    """Return one dict per LIVE_DEVICE_<N>_* slot that has a HOST set."""
    devices = []
    for i in range(1, MAX_DEVICE_SLOTS + 1):
        host = os.environ.get(f"LIVE_DEVICE_{i}_HOST", "")
        if not host:
            continue
        devices.append(
            {
                "id": f"device{i}",
                "host": host,
                "port": int(os.environ.get(f"LIVE_DEVICE_{i}_PORT", "80")),
                "salt_agent_password": os.environ.get(f"LIVE_DEVICE_{i}_SALT_AGENT_PASSWORD", ""),
                "root_password": os.environ.get(f"LIVE_DEVICE_{i}_ROOT_PASSWORD", ""),
                "ssh_port": int(os.environ.get(f"LIVE_DEVICE_{i}_SSH_PORT", "22")),
            }
        )
    return devices


def _device_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def make_rpc_client(device: dict):
    """Return an authenticated UbusRpcClient for the given device config.

    UbusRpcClient builds https:// by default; LAN devices without a cert
    serve plain HTTP, so we override the URL after construction.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.uci_ubus._internal.rpc import UbusRpcClient

    client = UbusRpcClient(
        host=device["host"],
        username="salt-agent",
        password=device["salt_agent_password"],
        port=device["port"],
        verify_ssl=False,
        timeout=10,
    )
    client.url = f"http://{device['host']}:{device['port']}/ubus"
    client.login()
    return client


def pytest_generate_tests(metafunc):
    if "device_config" in metafunc.fixturenames:
        devices = _configured_devices()
        metafunc.parametrize(
            "device_config",
            devices,
            ids=[d["id"] for d in devices],
            indirect=True,
            scope="module",
        )


@pytest.fixture(scope="module")
def device_config(request):
    return request.param


@pytest.fixture(scope="module")
def live_device(device_config):
    """Session-scoped-per-device fixture — skips this device's tests when
    unreachable or its salt-agent password is not set."""
    if not device_config["salt_agent_password"]:
        pytest.skip(f"LIVE_DEVICE_*_SALT_AGENT_PASSWORD not set for {device_config['id']}.")
    if not _device_reachable(device_config["host"], device_config["port"]):
        pytest.skip(
            f"Live device {device_config['id']} "
            f"({device_config['host']}:{device_config['port']}) is not reachable. "
            "Check network connectivity."
        )
    yield device_config


@pytest.fixture(scope="module")
def ubus_client(live_device):
    """Authenticated UbusRpcClient for the duration of this device's tests."""
    yield make_rpc_client(live_device)


@pytest.fixture(scope="module")
def uci_module(live_device):
    """Salt execution module wired to the live device.

    Injects the production ubus_jsonrpc → ubus_ops code path without
    requiring a running Salt master or proxy minion.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.uci_ubus.modules import ubus_jsonrpc as mod

    client = make_rpc_client(live_device)
    mod.__opts__ = {"proxy": {"proxytype": "uci_ubus_jsonrpc"}, "id": live_device["host"]}
    mod.__proxy__ = {"uci_ubus_jsonrpc.call": client.call}
    yield mod


@pytest.fixture(scope="module")
def ssh_client(live_device):
    """Paramiko SSH session as root — used for file-level read checks.

    Skipped when this device's ROOT_PASSWORD is not set; only SSH-dependent
    tests declare this fixture as a parameter.
    """
    if not live_device["root_password"]:
        pytest.skip(f"LIVE_DEVICE_*_ROOT_PASSWORD not set for {live_device['id']} — skipping SSH-dependent tests.")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
    client.connect(
        live_device["host"],
        port=live_device["ssh_port"],
        username="root",
        password=live_device["root_password"],
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
