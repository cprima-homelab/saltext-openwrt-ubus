# Known Bugs

## Proxy minion grains: `shell` leaks from proxy host

**Affected:** All saltext_uci proxy minions on Salt 3007.x

**Symptom:** `salt austru grains.get shell` returns `/bin/bash` (the
proxy host's shell) instead of `/bin/ash` (OpenWrt's default).

**Root cause:** Salt's built-in `extra.py` grains module sets
`__proxyenabled__ = ["*"]` and defines a `shell()` function that reads
`$SHELL` from the process environment. Built-in grains modules are
merged *after* extension grains, so `extra.py` overwrites the value
returned by the saltext_uci grains module.

**Impact:** `salt -G 'shell:/bin/ash'` targeting will not match OpenWrt
devices. All other grains correctly reflect the device, not the host.

**Workaround:** None from extension code. Requires an upstream Salt
change to make `extra.py` skip `shell()` for proxy minions, or to
change the grains merge order so extension grains take precedence over
built-in grains.

**Upstream:** Not yet filed.
