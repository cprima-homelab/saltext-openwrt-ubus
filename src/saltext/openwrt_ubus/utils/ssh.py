"""
SSH command runner for OpenWrt devices.

Pure Python, no Salt dependency. Executes commands over SSH via
subprocess and returns stdout. Analogous to ``utils/rpc.py``
(``UbusRpcClient``) but using SSH transport.
"""

import logging
import subprocess

log = logging.getLogger(__name__)


class SshCommandError(Exception):
    """Raised when an SSH command exits with a non-zero return code."""

    def __init__(self, returncode, stderr, command=None):
        self.returncode = returncode
        self.stderr = stderr
        self.command = command
        msg = f"SSH command failed (rc={returncode})"
        if command:
            msg += f": {command}"
        if stderr:
            msg += f"\n{stderr}"
        super().__init__(msg)


class SshRunner:
    """Execute commands on a remote host via SSH subprocess.

    Args:
        host: Remote hostname or IP address.
        username: SSH username (default ``root``).
        port: SSH port (default 22).
        ssh_options: List of extra ``-o`` options
            (e.g., ``["StrictHostKeyChecking=no",
            "IdentityFile=/path/to/key"]``).
        timeout: Default command timeout in seconds (default 30).
        control_path: Path for the ControlMaster Unix socket
            (e.g., ``/tmp/saltext-ssh-%r@%h:%p``). When set,
            OpenSSH connection multiplexing is enabled via
            ``ControlMaster=auto``. Default ``None`` (disabled).
        control_persist: Seconds to keep the master connection alive
            after the last session disconnects (default 60).
            Only used when *control_path* is set.
    """

    def __init__(
        self,
        host,
        username="root",
        port=22,
        ssh_options=None,
        timeout=30,
        control_path=None,
        control_persist=60,
    ):
        self.host = host
        self.username = username
        self.port = port
        self.ssh_options = ssh_options or []
        self.timeout = timeout
        self.control_path = control_path
        self.control_persist = control_persist

    def _build_ssh_args(self):
        """Build the base SSH argument list (without the remote command)."""
        args = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-p",
            str(self.port),
            "-l",
            self.username,
        ]
        if self.control_path:
            args.extend(
                [
                    "-o",
                    "ControlMaster=auto",
                    "-o",
                    f"ControlPath={self.control_path}",
                    "-o",
                    f"ControlPersist={self.control_persist}",
                ]
            )
        for opt in self.ssh_options:
            args.extend(["-o", opt])
        args.append(self.host)
        return args

    def run(self, command, timeout=None):
        """Execute a command on the remote host and return stdout.

        Args:
            command: The shell command string to run remotely.
            timeout: Override the default timeout (seconds).

        Returns:
            The command's stdout as a string (stripped).

        Raises:
            SshCommandError: If the command exits with a non-zero code.
            subprocess.TimeoutExpired: If the command exceeds the timeout.
        """
        args = self._build_ssh_args()
        args.append(command)
        effective_timeout = timeout if timeout is not None else self.timeout

        log.debug("SSH run: %s", args)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=effective_timeout,
        )

        if result.returncode != 0:
            raise SshCommandError(
                returncode=result.returncode,
                stderr=result.stderr.strip(),
                command=command,
            )
        return result.stdout.strip()

    def close_master(self):
        """Tear down the ControlMaster connection (if any).

        Sends ``ssh -O exit`` to ask the master process to shut down.
        Best-effort: errors are logged and silently ignored.
        """
        if not self.control_path:
            return
        args = [
            "ssh",
            "-o",
            f"ControlPath={self.control_path}",
            "-O",
            "exit",
            "-l",
            self.username,
            "-p",
            str(self.port),
            self.host,
        ]
        try:
            log.debug("SSH close_master: %s", args)
            subprocess.run(args, capture_output=True, text=True, check=False, timeout=5)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.debug("close_master ignoring error: %s", exc)

    def test_connection(self):
        """Test SSH connectivity with a simple ``echo`` command.

        Returns:
            True if the connection succeeds, False otherwise.
        """
        try:
            output = self.run("echo ok", timeout=10)
            return output == "ok"
        except (SshCommandError, subprocess.TimeoutExpired, OSError):
            return False
