# saltext.uci-ssh

Salt extension: OpenWrt UCI configuration management over SSH (runs
`ubus call` remotely and parses the JSON output). Requires `saltext.uci`.

## Install

```bash
pip install saltext.uci-ssh
```

## Configure

```yaml
# /srv/salt/pillar/router.sls
proxy:
  proxytype: uci_ssh
  host: 10.35.24.1
  # username: root                          (default)
  # port: 22                                (default)
  # timeout: 30                             (default)
  ssh_key: /root/.ssh/openwrt_ed25519
  # ssh_options:                            (defaults below)
  #   - StrictHostKeyChecking=no
  #   - UserKnownHostsFile=/dev/null
  #   - HostKeyAlgorithms=+ssh-rsa
  #   - PubkeyAcceptedAlgorithms=+ssh-rsa
  # ssh_multiplex: true                     (default, ControlMaster)
  # control_persist: 60                     (default, seconds)
```

```bash
salt router uci.get network
```

Docs: https://cprima-homelab.github.io/saltext-uci
