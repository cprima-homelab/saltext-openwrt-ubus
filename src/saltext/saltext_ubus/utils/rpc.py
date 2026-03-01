"""
JSON-RPC client for the OpenWrt ubus API.

Pure Python, no Salt dependency. Handles session authentication,
token refresh, and ubus method dispatch over HTTPS.
"""

import json
import logging
import ssl
import time
import urllib.request

log = logging.getLogger(__name__)

# ubus JSON-RPC result codes
UBUS_STATUS_OK = 0
UBUS_STATUS_INVALID_COMMAND = 1
UBUS_STATUS_INVALID_ARGUMENT = 2
UBUS_STATUS_METHOD_NOT_FOUND = 3
UBUS_STATUS_NOT_FOUND = 4
UBUS_STATUS_NO_DATA = 5
UBUS_STATUS_PERMISSION_DENIED = 6
UBUS_STATUS_TIMEOUT = 7

_STATUS_NAMES = {
    0: "OK",
    1: "Invalid command",
    2: "Invalid argument",
    3: "Method not found",
    4: "Not found",
    5: "No data",
    6: "Permission denied",
    7: "Timeout",
}

NULL_SESSION = "00000000000000000000000000000000"


class UbusError(Exception):
    """Raised when a ubus call returns a non-zero status code."""

    def __init__(self, code, message=None):
        self.code = code
        self.message = message or _STATUS_NAMES.get(code, f"Unknown error {code}")
        super().__init__(f"ubus error {code}: {self.message}")


class JsonRpcError(Exception):
    """Raised when the JSON-RPC envelope contains an error."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"JSON-RPC error {code}: {message}")


class UbusRpcClient:
    """Client for the OpenWrt ubus JSON-RPC API.

    Args:
        host: Device hostname or IP address.
        username: rpcd login username.
        password: rpcd login password.
        port: HTTPS port (default 443).
        verify_ssl: Whether to verify the TLS certificate (default False
            because OpenWrt uses self-signed certs).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, host, username, password, port=443, verify_ssl=False, timeout=30):
        self.url = f"https://{host}:{port}/ubus"
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session = None
        self._session_expires = 0
        self._session_timeout = 0
        self._req_id = 0

        self._ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _raw_request(self, method, params):
        """Send a raw JSON-RPC request and return the parsed response."""
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def login(self):
        """Authenticate and store the session token.

        Returns the session token string.
        """
        result = self._raw_request(
            "call",
            [
                NULL_SESSION,
                "session",
                "login",
                {
                    "username": self.username,
                    "password": self.password,
                },
            ],
        )
        if "error" in result:
            raise JsonRpcError(result["error"]["code"], result["error"]["message"])
        status = result["result"][0]
        if status != UBUS_STATUS_OK:
            raise UbusError(status)
        data = result["result"][1]
        self._session = data["ubus_rpc_session"]
        self._session_timeout = data.get("timeout", 300)
        self._session_expires = time.monotonic() + self._session_timeout - 10
        log.debug("ubus login OK, session=%s...%s", self._session[:8], self._session[-4:])
        return self._session

    @property
    def session_timeout(self):
        """Return the session timeout reported by rpcd at login."""
        return self._session_timeout

    def _ensure_session(self):
        """Re-login if the session has expired or was never created."""
        if self._session is None or time.monotonic() >= self._session_expires:
            self.login()

    def call(self, ubus_object, ubus_method, params=None):
        """Call a ubus method and return the result data.

        Args:
            ubus_object: ubus object path (e.g., "uci", "system").
            ubus_method: Method name (e.g., "get", "board").
            params: Dict of method parameters (default empty).

        Returns:
            The result data dict, or None for methods that return no body.

        Raises:
            UbusError: If the ubus status code is non-zero.
            JsonRpcError: If the JSON-RPC envelope has an error.
        """
        self._ensure_session()
        if params is None:
            params = {}

        result = self._raw_request(
            "call",
            [self._session, ubus_object, ubus_method, params],
        )

        if "error" in result:
            err = result["error"]
            if err.get("code") == -32002:
                raise UbusError(
                    UBUS_STATUS_PERMISSION_DENIED,
                    f"Access denied: {ubus_object}.{ubus_method}",
                )
            raise JsonRpcError(err["code"], err["message"])

        status = result["result"][0]
        if status != UBUS_STATUS_OK:
            raise UbusError(status)

        if len(result["result"]) > 1:
            return result["result"][1]
        return None
