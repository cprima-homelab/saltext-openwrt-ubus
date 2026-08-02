# saltext.uci-ubus

Salt extension: OpenWrt UCI configuration management via ubus (JSON-RPC,
or local ubus CLI through `salt-ssh`). Requires `saltext.uci`.

## Install

```bash
pip install saltext.uci-ubus
```

## Configure

```yaml
# /srv/salt/pillar/router.sls
proxy:
  proxytype: uci_ubus_jsonrpc
  host: 10.35.24.1
  password: secret
  # username: salt-agent      (default)
  # scheme: https             (auto-detected by default: tries plain
  # port: 443                  HTTP on 80 first, falls back to HTTPS on
  #                            443 -- set both explicitly to skip probing,
  #                            e.g. for a device behind Caddy/ACME)
  # verify_ssl: false         (default)
  # timeout: 30               (default, HTTP request timeout)
```

```bash
salt router uci.get network
```

Docs: https://cprima-homelab.github.io/saltext-uci
