"""
Fixtures for saltext-uci integration tests against a live openwrt/rootfs container.

Start the environment before running these tests:
    docker compose -f infra/openwrt-test/compose.yaml up -d

Override connection via environment variables:
    UBUS_HOST, UBUS_PORT, SALT_AGENT_PASSWORD, CONTAINER_NAME
"""

import os
import subprocess
from pathlib import Path

import pytest

UBUS_HOST = os.environ.get("UBUS_HOST", "localhost")
UBUS_PORT = int(os.environ.get("UBUS_PORT", "7080"))
UBUS_URL = f"http://{UBUS_HOST}:{UBUS_PORT}/ubus"
SALT_AGENT_PASSWORD = os.environ.get("SALT_AGENT_PASSWORD", "test1234")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "openwrt-test-target")

# Single source of truth for testcorpus test cases.
TESTCORPUS_TESTS = Path(__file__).parents[3] / "infra/openwrt-test/fixtures/tests"


def docker_exec(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """Run `docker exec <args>` with MSYS_NO_PATHCONV=1 to prevent Git Bash
    from rewriting container-internal paths like /etc/config/ on Windows."""
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(
        ["docker", "exec", *args],
        env=env,
        input=stdin,
        check=True,
        text=stdin is None,
        capture_output=True,
    )


def _container_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


@pytest.fixture(scope="session")
def openwrt_container():
    """Session fixture — skips entire module if container is not running."""
    if not _container_running():
        pytest.skip(
            f"Container '{CONTAINER_NAME}' is not running. "
            f"Start it with: docker compose -f infra/openwrt-test/compose.yaml up -d"
        )
    yield CONTAINER_NAME


def make_rpc_client():
    """Return an authenticated UbusRpcClient connected to the test container.

    UbusRpcClient always builds an https:// URL from host+port.  The test
    container only serves plain HTTP, so we override the URL after construction.
    This is intentional test-setup plumbing — production targets use HTTPS.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.openwrt_ubus.utils.rpc import UbusRpcClient

    client = UbusRpcClient(
        host=UBUS_HOST,
        username="salt-agent",
        password=SALT_AGENT_PASSWORD,
        port=UBUS_PORT,
        verify_ssl=False,
        timeout=10,
    )
    client.url = UBUS_URL  # override https:// → http://
    client.login()
    return client


@pytest.fixture(scope="session")
def ubus_client(openwrt_container):  # pylint: disable=unused-argument
    """Authenticated UbusRpcClient for the duration of the test session."""
    yield make_rpc_client()


@pytest.fixture
def testcorpus_case(request, openwrt_container):
    """
    Parametrize with a testcorpus case name, e.g. '01_set_scalar_named'.
    Resets /etc/config/testcorpus to that case's before.uci before the test runs.
    Returns the case name so tests can load delta.yaml and after.uci themselves.
    """
    case_name = request.param
    before_uci = (TESTCORPUS_TESTS / case_name / "before.uci").read_bytes()
    docker_exec(
        "-i", openwrt_container, "sh", "-c", "cat > /etc/config/testcorpus", stdin=before_uci
    )
    return case_name


def read_container_config(container_name: str, config: str) -> str:
    """Read /etc/config/<config> from the running container."""
    return docker_exec(container_name, "cat", f"/etc/config/{config}").stdout
