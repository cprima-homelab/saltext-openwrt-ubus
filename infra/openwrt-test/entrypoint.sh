#!/bin/sh
# Startup sequence for the saltext-uci integration test environment.
# Brings up ubusd → rpcd → uhttpd in the correct dependency order,
# then resets /etc/config from the mounted fixture or the baked-in pristine copy.
set -e

# OpenWrt 24.x: ubusd creates socket at /var/run/ubus/ubus.sock.
UBUS_SOCK="/var/run/ubus/ubus.sock"

mkdir -p /var/run/ubus /var/lock /tmp /www

# 1. ubus daemon — everything else depends on the socket being present.
ubusd &

# Poll for socket; BusyBox sleep only accepts integers.
i=0
while [ ! -S "$UBUS_SOCK" ]; do
    i=$((i + 1))
    [ $i -gt 10 ] && echo "ubusd: socket never appeared at $UBUS_SOCK" >&2 && exit 1
    sleep 1
done

# 2. rpcd — reads /etc/config/rpcd for logins, /usr/share/rpcd/acl.d/ for ACL.
rpcd -s "$UBUS_SOCK" &
sleep 1

# 3. Reset /etc/config from mounted fixture (preferred) or baked-in pristine copy.
#    Mount a fixture directory at /fixture to override the default testcorpus state.
if [ -d /fixture ] && [ "$(ls -A /fixture 2>/dev/null)" ]; then
    echo "Loading fixture from /fixture"
    cp -r /fixture/. /etc/config/
else
    echo "Loading pristine testcorpus fixture"
    cp -r /etc/config-pristine/. /etc/config/
fi

# 4. uhttpd — foreground as PID 1.
#    -u /ubus   : URL prefix for JSON-RPC handler (uhttpd-mod-ubus)
#    -U $SOCK   : ubus socket path override (default would be /var/run/ubus.sock)
exec uhttpd -f -h /www -p 0.0.0.0:80 -u /ubus -U "$UBUS_SOCK"
