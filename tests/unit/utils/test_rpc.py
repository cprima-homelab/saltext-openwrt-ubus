"""
Unit tests for the ubus JSON-RPC client.

All tests use mocked HTTP responses. No network calls are made.
"""

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from saltext.saltext_ubus.utils.rpc import NULL_SESSION
from saltext.saltext_ubus.utils.rpc import UBUS_STATUS_OK
from saltext.saltext_ubus.utils.rpc import UBUS_STATUS_PERMISSION_DENIED
from saltext.saltext_ubus.utils.rpc import JsonRpcError
from saltext.saltext_ubus.utils.rpc import UbusError
from saltext.saltext_ubus.utils.rpc import UbusRpcClient


def _jsonrpc_response(result=None, error=None, req_id=1):
    """Build a mock JSON-RPC response body."""
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    if result is not None:
        resp["result"] = result
    return json.dumps(resp).encode("utf-8")


def _mock_urlopen(body):
    """Return a context-manager-compatible mock for urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestClientInit:
    def test_url_construction(self):
        client = UbusRpcClient("10.0.0.1", "user", "pass")
        assert client.url == "https://10.0.0.1:443/ubus"

    def test_custom_port(self):
        client = UbusRpcClient("10.0.0.1", "user", "pass", port=8443)
        assert client.url == "https://10.0.0.1:8443/ubus"

    def test_no_session_initially(self):
        client = UbusRpcClient("10.0.0.1", "user", "pass")
        assert client._session is None


class TestLogin:
    def test_successful_login(self):
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        body = _jsonrpc_response(
            result=[UBUS_STATUS_OK, {"ubus_rpc_session": "abc123def456", "timeout": 300}]
        )
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            token = client.login()
        assert token == "abc123def456"
        assert client._session == "abc123def456"

    def test_login_permission_denied(self):
        client = UbusRpcClient("10.0.0.1", "salt", "wrong")
        body = _jsonrpc_response(result=[UBUS_STATUS_PERMISSION_DENIED])
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            with pytest.raises(UbusError) as exc_info:
                client.login()
            assert exc_info.value.code == UBUS_STATUS_PERMISSION_DENIED

    def test_login_jsonrpc_error(self):
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        body = _jsonrpc_response(error={"code": -32600, "message": "Invalid request"})
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            with pytest.raises(JsonRpcError) as exc_info:
                client.login()
            assert exc_info.value.code == -32600

    def test_login_sends_null_session(self):
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        body = _jsonrpc_response(
            result=[UBUS_STATUS_OK, {"ubus_rpc_session": "tok", "timeout": 300}]
        )
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            client.login()
            # Extract the request body
            call_args = mock_open.call_args
            req = call_args[0][0]
            sent = json.loads(req.data)
            assert sent["params"][0] == NULL_SESSION

    def test_login_passes_session_timeout(self):
        """session_timeout kwarg is forwarded as 'timeout' in login params."""
        client = UbusRpcClient("10.0.0.1", "salt", "pass", session_timeout=600)
        body = _jsonrpc_response(
            result=[UBUS_STATUS_OK, {"ubus_rpc_session": "tok", "timeout": 600}]
        )
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            client.login()
            req = mock_open.call_args[0][0]
            sent = json.loads(req.data)
            login_params = sent["params"][3]
            assert login_params["timeout"] == 600
        assert client.session_timeout == 600

    def test_login_omits_timeout_when_not_set(self):
        """When session_timeout is None, no timeout key in login params."""
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        body = _jsonrpc_response(
            result=[UBUS_STATUS_OK, {"ubus_rpc_session": "tok", "timeout": 300}]
        )
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            client.login()
            req = mock_open.call_args[0][0]
            sent = json.loads(req.data)
            login_params = sent["params"][3]
            assert "timeout" not in login_params


class TestCall:
    def _make_client(self):
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        client._session = "active_token"
        client._session_expires = float("inf")
        return client

    def test_successful_call_with_data(self):
        client = self._make_client()
        body = _jsonrpc_response(result=[UBUS_STATUS_OK, {"configs": ["network"]}])
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = client.call("uci", "configs")
        assert result == {"configs": ["network"]}

    def test_call_no_data_returns_none(self):
        client = self._make_client()
        body = _jsonrpc_response(result=[UBUS_STATUS_OK])
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = client.call("uci", "confirm", {})
        assert result is None

    def test_auto_relogin_on_no_session(self):
        client = UbusRpcClient("10.0.0.1", "salt", "pass")
        # No session set -> triggers login first
        login_body = _jsonrpc_response(
            result=[UBUS_STATUS_OK, {"ubus_rpc_session": "new_tok", "timeout": 300}]
        )
        call_body = _jsonrpc_response(result=[UBUS_STATUS_OK, {"configs": ["network"]}])
        responses = iter([_mock_urlopen(login_body), _mock_urlopen(call_body)])
        with patch("urllib.request.urlopen", side_effect=lambda *a, **kw: next(responses)):
            result = client.call("uci", "configs")
        assert result == {"configs": ["network"]}
        assert client._session == "new_tok"

    def test_permission_denied_error_code(self):
        client = self._make_client()
        body = _jsonrpc_response(error={"code": -32002, "message": "Access denied"})
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            with pytest.raises(UbusError) as exc_info:
                client.call("uci", "set", {"config": "network"})
            assert exc_info.value.code == UBUS_STATUS_PERMISSION_DENIED

    def test_ubus_status_error(self):
        client = self._make_client()
        body = _jsonrpc_response(result=[4])  # UBUS_STATUS_NOT_FOUND
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            with pytest.raises(UbusError) as exc_info:
                client.call("uci", "get", {"config": "nonexistent"})
            assert exc_info.value.code == 4

    def test_jsonrpc_error(self):
        client = self._make_client()
        body = _jsonrpc_response(error={"code": -32700, "message": "Parse error"})
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            with pytest.raises(JsonRpcError):
                client.call("uci", "get", {"config": "network"})

    def test_call_sends_session_token(self):
        client = self._make_client()
        body = _jsonrpc_response(result=[UBUS_STATUS_OK, {}])
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            client.call("uci", "get", {"config": "network"})
            req = mock_open.call_args[0][0]
            sent = json.loads(req.data)
            assert sent["params"][0] == "active_token"
            assert sent["params"][1] == "uci"
            assert sent["params"][2] == "get"
            assert sent["params"][3] == {"config": "network"}

    def test_call_default_params_empty_dict(self):
        client = self._make_client()
        body = _jsonrpc_response(result=[UBUS_STATUS_OK, {}])
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock_open:
            client.call("system", "board")
            req = mock_open.call_args[0][0]
            sent = json.loads(req.data)
            assert sent["params"][3] == {}


class TestErrorMessages:
    def test_ubus_error_str(self):
        err = UbusError(6)
        assert "Permission denied" in str(err)

    def test_ubus_error_unknown_code(self):
        err = UbusError(99)
        assert "Unknown error 99" in str(err)

    def test_jsonrpc_error_str(self):
        err = JsonRpcError(-32600, "Invalid request")
        assert "Invalid request" in str(err)
