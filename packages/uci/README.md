# saltext.uci

Core UCI data model, diffing, and state logic for OpenWrt device
management. Transport-agnostic -- no execution module, no proxy, nothing
that can talk to a device on its own.

## Install

You normally don't install this directly -- it's a dependency of the
transport package you actually want:

```bash
pip install saltext.uci-ubus   # ubus / JSON-RPC transport
pip install saltext.uci-ssh    # SSH transport
```

Either pulls in `saltext.uci` automatically.

Docs: https://cprima-homelab.github.io/saltext-uci
