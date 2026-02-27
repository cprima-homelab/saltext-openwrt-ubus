# System Administration Changes -- 2026-02-27

Manual changes made to live routers during exploratory session.
Each change includes exact revert commands.

---

## austru (10.35.24.1, OpenWrt 24.10.5)

### 1. Created system user `salt`

**What was done:**

Added a system user `salt` (uid 1000, gid 1000) for rpcd/JSON-RPC
authentication. The password hash is stored in both `/etc/passwd` and
`/etc/shadow`.

```sh
# Line appended to /etc/passwd:
salt:$5$E3pBNJZWPqNCrCqL$eGcw/pyaCeucuWzN/m6yzXZWhqWtGC5sPC87b1dtYg0:1000:1000:salt:/home/salt:/bin/ash

# Line appended to /etc/group:
salt:x:1000:

# Line appended to /etc/shadow:
salt:$5$E3pBNJZWPqNCrCqL$eGcw/pyaCeucuWzN/m6yzXZWhqWtGC5sPC87b1dtYg0:19864:0:99999:7:::

# Home directory created:
/home/salt/   (owned by root:root, empty)
```

The password is `bntTSs5oczGOjLVEZyYe` (stored in `saltext-uci/.env`,
gitignored). The hash uses SHA-256 (`$5$` prefix).

Note: BusyBox `passwd` on OpenWrt wrote the hash directly into
`/etc/passwd` (field 2) because there was no pre-existing `/etc/shadow`
entry. The shadow entry was added manually afterward by copying the hash
from `/etc/passwd`. The hash in `/etc/passwd` field 2 was NOT cleaned up
(it should ideally be `x` with the hash only in `/etc/shadow`).

**How to revert:**

```sh
ssh austru '
  sed -i "/^salt:/d" /etc/passwd
  sed -i "/^salt:/d" /etc/shadow
  sed -i "/^salt:/d" /etc/group
  rm -rf /home/salt
'
```

Verify:

```sh
ssh austru 'id salt 2>&1; grep salt /etc/passwd /etc/shadow /etc/group'
# Expected: "id: unknown user salt" and no grep output
```

---

### 2. Added rpcd login for `salt` user

**What was done:**

Added a UCI config section to `/etc/config/rpcd` granting the `salt` user
full read/write access to all rpcd access groups. The password uses `$p$salt`
which tells rpcd to verify credentials against the system password in
`/etc/shadow`.

```
rpcd.cfg03f8be=login
rpcd.cfg03f8be.username='salt'
rpcd.cfg03f8be.password='$p$salt'
rpcd.cfg03f8be.read='*'
rpcd.cfg03f8be.write='*'
```

Commands used:

```sh
uci add rpcd login
uci set rpcd.@login[-1].username='salt'
uci set "rpcd.@login[-1].password=$""p$""salt"   # workaround for $ escaping
uci add_list rpcd.@login[-1].read='*'
uci add_list rpcd.@login[-1].write='*'
uci commit rpcd
/etc/init.d/rpcd restart
```

The ACLs were initially set to `read: *, write: network uci` but were
broadened to `read: *, write: *` during exploration after discovering that
many ubus calls require access groups defined in LuCI ACL files.

**How to revert:**

```sh
ssh austru '
  uci delete rpcd.@login[1]
  uci commit rpcd
  /etc/init.d/rpcd restart
'
```

Verify:

```sh
ssh austru 'uci show rpcd'
# Expected: only rpcd.@login[0] (root) remains
```

**Security note:** The `write: *` grants full write access to all ubus
objects and UCI packages that have ACL definitions. This is appropriate
for exploration but should be narrowed for production use. See
`docs/devops/code/06-rpcd-acl-model.md` for a scoped ACL definition.

---

### 3. No changes to uhttpd

The `/ubus` endpoint was already configured (`uhttpd.main.ubus_prefix='/ubus'`)
and `uhttpd-mod-ubus` was already installed. No changes were made to uhttpd.

---

### Summary of changed files on austru

| File              | Change                                     | Persists across reboot |
|-------------------|--------------------------------------------|------------------------|
| `/etc/passwd`     | Added `salt` user line (with password hash)| Yes                    |
| `/etc/shadow`     | Added `salt` user line                     | Yes                    |
| `/etc/group`      | Added `salt` group line                    | Yes                    |
| `/home/salt/`     | Created empty directory                    | Yes (overlay)          |
| `/etc/config/rpcd`| Added login section for salt               | Yes                    |

All files are on the overlay filesystem and survive reboots. A factory
reset (`firstboot`) would remove all of them.

---

## autan (10.38.20.1, OpenWrt remote site)

### 4. Added DNS domain entry for `austru`

**What was done:**

Added a dnsmasq domain record so devices on autan's LAN can resolve
`austru` to `10.35.24.1` (reachable via site-to-site VPN).

```
dhcp.cfg3af37d=domain
dhcp.cfg3af37d.name='austru'
dhcp.cfg3af37d.ip='10.35.24.1'
```

Commands used:

```sh
ssh autan '
  uci add dhcp domain
  uci set dhcp.@domain[-1].name="austru"
  uci set dhcp.@domain[-1].ip="10.35.24.1"
  uci commit dhcp
  /etc/init.d/dnsmasq restart
'
```

This is a `config domain` entry (DNS-only), not a `config host` (DHCP
static lease). It tells dnsmasq to answer queries for `austru` with
`10.35.24.1` but does not assign DHCP leases or MAC bindings.

**How to revert:**

The domain entry is anonymous. Find it by name, then delete:

```sh
ssh autan '
  # Find the index of the austru domain entry
  i=0
  while uci -q get "dhcp.@domain[$i]" >/dev/null; do
    if [ "$(uci -q get dhcp.@domain[$i].name)" = "austru" ]; then
      uci delete "dhcp.@domain[$i]"
      uci commit dhcp
      /etc/init.d/dnsmasq restart
      echo "deleted domain entry at index $i"
      break
    fi
    i=$((i + 1))
  done
'
```

Verify:

```sh
ssh autan 'uci show dhcp | grep austru'
# Expected: no output
```

---

### Summary of changed files on autan

| File              | Change                              | Persists across reboot |
|-------------------|-------------------------------------|------------------------|
| `/etc/config/dhcp`| Added domain entry for `austru`     | Yes                    |

---

## Full revert (all changes, both routers)

Run in order:

```sh
# 1. Remove rpcd login on austru
ssh austru '
  uci delete rpcd.@login[1]
  uci commit rpcd
  /etc/init.d/rpcd restart
'

# 2. Remove salt user on austru
ssh austru '
  sed -i "/^salt:/d" /etc/passwd
  sed -i "/^salt:/d" /etc/shadow
  sed -i "/^salt:/d" /etc/group
  rm -rf /home/salt
'

# 3. Remove DNS entry on autan
ssh autan '
  i=0
  while uci -q get "dhcp.@domain[$i]" >/dev/null; do
    if [ "$(uci -q get dhcp.@domain[$i].name)" = "austru" ]; then
      uci delete "dhcp.@domain[$i]"
      uci commit dhcp
      /etc/init.d/dnsmasq restart
      break
    fi
    i=$((i + 1))
  done
'

# 4. Delete .env file
rm D:/github.com/cprima-homelab/saltext-uci/.env
```
