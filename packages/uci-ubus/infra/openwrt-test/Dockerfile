FROM openwrt/rootfs:x86_64-v24.10.8

# opkg needs /var/lock and /var/run which are absent in the bare rootfs.
RUN mkdir -p /var/lock /var/run /tmp

# Install runtime dependencies for ubus JSON-RPC over HTTP.
# uhttpd-mod-ubus exposes /ubus endpoint; rpcd handles sessions + ACL.
RUN opkg update && opkg install rpcd uhttpd uhttpd-mod-ubus

# ACL granting salt-agent access to uci/system/network ubus objects.
COPY acl/salt-agent-ubus.json /usr/share/rpcd/acl.d/salt-agent-ubus.json

# Create salt-agent system user (locked password — set at build time below).
RUN uid=499; \
    echo "salt-agent:x:${uid}:${uid}:salt-agent:/home/salt-agent:/bin/false" >> /etc/passwd && \
    echo "salt-agent:x:${uid}:" >> /etc/group && \
    echo "salt-agent:!:0:0:99999:7:::" >> /etc/shadow && \
    mkdir -p /home/salt-agent

# Set a fixed test password. rpcd verifies against /etc/shadow via $p$salt-agent.
# VERIFY: busybox passwd behaviour in this image — fallback is openssl passwd -6.
RUN printf 'test1234\ntest1234\n' | passwd salt-agent

# Register salt-agent rpcd login entry (reads /etc/config/rpcd at rpcd start).
RUN uci add rpcd login && \
    uci set "rpcd.@login[-1].username=salt-agent" && \
    uci set "rpcd.@login[-1].password=\$p\$salt-agent" && \
    uci add_list "rpcd.@login[-1].read=saltext-uci" && \
    uci add_list "rpcd.@login[-1].write=saltext-uci" && \
    uci commit rpcd

# Pristine fixture copy — entrypoint resets /etc/config from here on every start.
COPY fixtures/ /etc/config-pristine/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=15s \
    CMD ubus -t 1 list session || exit 1

ENTRYPOINT ["/entrypoint.sh"]
