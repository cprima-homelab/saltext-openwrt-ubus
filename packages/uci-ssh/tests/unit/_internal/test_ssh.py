"""
Unit tests for the SSH runner utility.

All tests mock subprocess.run. No SSH connections are made.
"""

import subprocess
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from saltext.uci_ssh._internal.ssh import SshCommandError
from saltext.uci_ssh._internal.ssh import SshRunner


@pytest.fixture
def runner():
    """Create a default SshRunner."""
    return SshRunner(host="10.0.0.1")


@pytest.fixture
def runner_custom():
    """Create an SshRunner with custom options."""
    return SshRunner(
        host="192.168.1.1",
        username="admin",
        port=2222,
        ssh_options=["StrictHostKeyChecking=no", "ConnectTimeout=5"],
        timeout=60,
    )


@pytest.fixture
def runner_mux():
    """Create an SshRunner with ControlMaster enabled."""
    return SshRunner(
        host="10.0.0.1",
        control_path="/tmp/saltext-ssh-%r@%h:%p",
        control_persist=120,
    )


class TestBuildSshArgs:
    def test_default_args(self, runner):
        args = runner._build_ssh_args()
        assert args == [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-p",
            "22",
            "-l",
            "root",
            "10.0.0.1",
        ]

    def test_custom_args(self, runner_custom):
        args = runner_custom._build_ssh_args()
        assert args == [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-p",
            "2222",
            "-l",
            "admin",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            "192.168.1.1",
        ]

    def test_control_master_args(self, runner_mux):
        args = runner_mux._build_ssh_args()
        assert args == [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-p",
            "22",
            "-l",
            "root",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPath=/tmp/saltext-ssh-%r@%h:%p",
            "-o",
            "ControlPersist=120",
            "10.0.0.1",
        ]

    def test_no_control_master_when_path_is_none(self, runner):
        args = runner._build_ssh_args()
        for arg in args:
            assert "ControlMaster" not in arg
            assert "ControlPath" not in arg
            assert "ControlPersist" not in arg


class TestRun:
    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_success(self, mock_run, runner):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"result": "ok"}\n',
            stderr="",
        )
        result = runner.run("ubus call system board")
        assert result == '{"result": "ok"}'
        mock_run.assert_called_once_with(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-p",
                "22",
                "-l",
                "root",
                "10.0.0.1",
                "ubus call system board",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run, runner):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Permission denied\n",
        )
        with pytest.raises(SshCommandError) as exc_info:
            runner.run("ubus call system board")
        assert exc_info.value.returncode == 1
        assert "Permission denied" in exc_info.value.stderr

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_timeout_override(self, mock_run, runner):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        runner.run("echo ok", timeout=5)
        assert mock_run.call_args[1]["timeout"] == 5

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_default_timeout(self, mock_run, runner):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        runner.run("echo ok")
        assert mock_run.call_args[1]["timeout"] == 30

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_timeout_expired(self, mock_run, runner):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=30)
        with pytest.raises(subprocess.TimeoutExpired):
            runner.run("sleep 999")

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_command_in_error(self, mock_run, runner):
        mock_run.return_value = MagicMock(
            returncode=127,
            stdout="",
            stderr="command not found",
        )
        with pytest.raises(SshCommandError) as exc_info:
            runner.run("nonexistent")
        assert exc_info.value.command == "nonexistent"
        assert exc_info.value.returncode == 127


class TestCloseMaster:
    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_sends_exit_command(self, mock_run, runner_mux):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        runner_mux.close_master()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "-O" in args
        assert "exit" in args
        assert "ControlPath=/tmp/saltext-ssh-%r@%h:%p" in args

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_noop_when_no_control_path(self, mock_run, runner):
        runner.close_master()
        mock_run.assert_not_called()

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_ignores_errors(self, mock_run, runner_mux):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=5)
        runner_mux.close_master()  # should not raise


class TestTestConnection:
    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_success(self, mock_run, runner):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        assert runner.test_connection() is True

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_failure_nonzero(self, mock_run, runner):
        mock_run.return_value = MagicMock(returncode=255, stdout="", stderr="Connection refused")
        assert runner.test_connection() is False

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_failure_timeout(self, mock_run, runner):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=10)
        assert runner.test_connection() is False

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_failure_oserror(self, mock_run, runner):
        mock_run.side_effect = OSError("ssh not found")
        assert runner.test_connection() is False

    @patch("saltext.uci_ssh._internal.ssh.subprocess.run")
    def test_wrong_output(self, mock_run, runner):
        mock_run.return_value = MagicMock(returncode=0, stdout="unexpected\n", stderr="")
        assert runner.test_connection() is False
