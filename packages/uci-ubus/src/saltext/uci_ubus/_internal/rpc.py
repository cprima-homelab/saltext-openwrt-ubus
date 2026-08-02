"""
JSON-RPC client for the OpenWrt ubus API.

Pure Python, no Salt dependency. Handles session authentication,
token refresh, and ubus method dispatch over HTTP or HTTPS (auto-detected).
"""

import http.client
import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.parse
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disables automatic redirect-following, so a 3xx always surfaces as an
    explicit HTTPError (with the Location header intact) instead of being
    silently followed or raised from deep in urllib's own handler chain."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _SNIOverrideHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects to self.host:self.port as usual, but
    presents a different name for TLS SNI (and the resulting Host header) —
    for reverse proxies (e.g. Caddy with a per-domain ACME cert) where the
    cert identity doesn't match whatever generic name we resolved to reach
    the device's IP."""

    def __init__(self, *args, tls_server_name=None, **kwargs):
        self._tls_server_name = tls_server_name
        super().__init__(*args, **kwargs)

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout, self.source_address)
        server_hostname = self._tls_server_name or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _SNIOverrideHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPSHandler that builds connections via _SNIOverrideHTTPSConnection."""

    def __init__(self, context, tls_server_name):
        super().__init__(context=context)
        self._tls_server_name = tls_server_name

    def https_open(self, req):
        def build_conn(host, **kwargs):
            kwargs.pop("context", None)
            return _SNIOverrideHTTPSConnection(
                host, context=self._context, tls_server_name=self._tls_server_name, **kwargs
            )

        return self.do_open(build_conn, req)


class UbusRpcClient:
    """Client for the OpenWrt ubus JSON-RPC API.

    Args:
        host: Device hostname or IP address.
        username: rpcd login username.
        password: rpcd login password.
        port: Port number. Omit to auto-detect (default).
        scheme: URL scheme, ``"https"`` or ``"http"``. Omit to auto-detect
            (default). Discovery explicitly handles: stock OpenWrt uhttpd
            (plain HTTP on 80), and a same-origin redirect to a
            TLS-terminating reverse proxy (e.g. Caddy with ACME, typically
            HTTPS on 443) — since uhttpd serves both LuCI and /ubus on the
            same listener, fronting one fronts the other. Anything past
            that (nonstandard ports, a proxy in front of a different
            backend, multi-hop redirects) is out of scope for discovery —
            set scheme and port explicitly instead.
        verify_ssl: Whether to verify the TLS certificate (default False
            because OpenWrt uses self-signed certs by default).
            Set to True when the target has a CA-signed cert (e.g. Caddy
            with ACME).
        server_name: Override TLS SNI and the HTTP Host header to this name
            instead of ``host``. Needed when ``host`` is a generic alias
            used only to resolve the device's address, but a reverse proxy
            in front of it (e.g. Caddy) routes by a specific domain name
            tied to its certificate — both its TLS layer (SNI) and its HTTP
            layer (Host header) need that real name to find the right site,
            independent of whichever name got you to its IP.
        timeout: HTTP request timeout in seconds.
        session_timeout: rpcd session timeout in seconds, passed to
            ``session login``. rpcd's compiled-in default is 300s.
    """

    def __init__(
        self,
        host,
        username,
        password,
        port=None,
        scheme=None,
        verify_ssl=False,
        server_name=None,
        timeout=30,
        session_timeout=None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.server_name = server_name
        self._requested_session_timeout = session_timeout
        self._session = None
        self._session_expires = 0
        self._session_timeout = 0
        self._req_id = 0

        self.url = f"{scheme}://{host}:{port}/ubus" if scheme and port else None

        self._ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

        https_handler = (
            _SNIOverrideHTTPSHandler(self._ssl_ctx, server_name)
            if server_name
            else urllib.request.HTTPSHandler(context=self._ssl_ctx)
        )
        # Normal opener (follows redirects) for once the endpoint is known;
        # a separate no-redirect variant for discovery, to see 3xx responses
        # explicitly instead of having them silently followed or auto-raised.
        self._opener = urllib.request.build_opener(https_handler)
        self._probe_opener = urllib.request.build_opener(_NoRedirect, https_handler)

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _raw_request(self, method, params):
        """Send a raw JSON-RPC request and return the parsed response.

        If the endpoint (scheme/port) hasn't been discovered yet, runs
        discovery first and locks in whatever it finds; otherwise sends
        directly through the already-known URL.
        """
        if self.url is None:
            return self._discover_ubus_endpoint(method, params)
        return self._send(self.url, method, params)

    def _build_request(self, url, method, params):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.server_name:
            # Caddy (and similar name-based vhost proxies) route by the HTTP
            # Host header too, not just TLS SNI — both need the real name.
            headers["Host"] = self.server_name
        return urllib.request.Request(url, data=body, headers=headers, method="POST")

    def _send(self, url, method, params):
        """Send through the normal opener, once the endpoint is known."""
        req = self._build_request(url, method, params)
        with self._opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _probe(self, url, method, params):
        """Send one discovery attempt through the no-redirect opener."""
        req = self._build_request(url, method, params)
        with self._probe_opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    #: Seed candidates for ubus discovery — what we explicitly claim to
    #: handle out of the box: stock OpenWrt's uhttpd default (plain HTTP on
    #: 80), and the common case of a TLS-terminating reverse proxy in front
    #: of it (HTTPS on 443, e.g. Caddy with ACME) — since uhttpd serves both
    #: LuCI and /ubus on the same listener, fronting one fronts the other.
    _SEED_CANDIDATES = (("http", 80), ("https", 443))
    _MAX_PROBE_ATTEMPTS = 4  # 2 seeds + up to 2 redirect hops

    def _discover_ubus_endpoint(self, method, params):
        """Try candidate URLs from a flat, growing queue — seeded with
        _SEED_CANDIDATES, extended by any same-origin redirect encountered
        along the way — until one actually responds with a genuine ubus
        JSON-RPC envelope. Everything beyond that (nonstandard ports, a
        redirect to a different backend, more than a couple of hops) is
        out of scope: set scheme/port explicitly instead of relying on this.
        """
        queue = [f"{scheme}://{self.host}:{port}/ubus" for scheme, port in self._SEED_CANDIDATES]
        tried = set()
        last_exc = None

        while queue and len(tried) < self._MAX_PROBE_ATTEMPTS:
            url = queue.pop(0)
            if url in tried:
                continue
            tried.add(url)

            try:
                result = self._probe(url, method, params)
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    location = exc.headers.get("Location") if exc.headers else None
                    if location:
                        target = urllib.parse.urljoin(url, location)
                        if target not in tried:
                            queue.append(target)
                    log.debug("ubus probe %s redirected (%d) to %s", url, exc.code, location)
                else:
                    log.debug("ubus probe %s returned HTTP %d", url, exc.code)
                last_exc = exc
                continue
            except urllib.error.URLError as exc:
                log.debug("ubus probe %s failed: %s", url, exc)
                last_exc = exc
                continue
            except ValueError as exc:  # not parseable as JSON
                log.debug("ubus probe %s returned non-JSON body: %s", url, exc)
                last_exc = exc
                continue

            if not isinstance(result, dict) or "jsonrpc" not in result:
                log.debug("ubus probe %s returned a non-ubus response", url)
                last_exc = ValueError(f"non-ubus response from {url}")
                continue

            self.url = url
            log.info("Discovered ubus endpoint for %s: %s", self.host, url)
            return result

        raise ConnectionError(
            f"Could not find a working ubus JSON-RPC endpoint on {self.host} "
            f"(tried: {', '.join(sorted(tried)) or 'none'})"
        ) from last_exc

    def login(self):
        """Authenticate and store the session token.

        Returns the session token string.
        """
        login_params = {
            "username": self.username,
            "password": self.password,
        }
        if self._requested_session_timeout is not None:
            login_params["timeout"] = self._requested_session_timeout

        result = self._raw_request(
            "call",
            [NULL_SESSION, "session", "login", login_params],
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
