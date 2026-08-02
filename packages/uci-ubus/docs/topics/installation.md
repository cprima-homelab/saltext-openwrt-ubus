# Installation

Generally, extensions need to be installed into the same Python environment Salt uses.

:::{tab} State
```yaml
Install Salt openwrt-ubus extension:
  pip.installed:
    - name: saltext-uci-ubus
```
:::

:::{tab} Onedir installation
```bash
salt-pip install saltext-uci-ubus
```
:::

:::{tab} Regular installation
```bash
pip install saltext-uci-ubus
```
:::

:::{hint}
Saltexts are not distributed automatically via the fileserver like custom modules, they need to be installed
on each node you want them to be available on.
:::
