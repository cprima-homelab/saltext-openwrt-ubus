include $(TOPDIR)/rules.mk

PKG_NAME:=salt-agent-ubus
PKG_VERSION:=0.2.0
PKG_RELEASE:=1

PKG_MAINTAINER:=Christian Prior-Mamulyan <cprior@gmail.com>
PKG_LICENSE:=Apache-2.0
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/salt-agent-ubus
  SECTION:=admin
  CATEGORY:=Administration
  TITLE:=Salt agent for OpenWrt ubus JSON-RPC transport
  DEPENDS:=+rpcd +uhttpd-mod-ubus
  PKGARCH:=all
endef

define Package/salt-agent-ubus/description
  Creates a salt-agent system user with rpcd login and installs ACL
  rules granting scoped access to UCI, network, and system ubus
  objects via the JSON-RPC API. Used by the saltext-ubus Salt extension
  to manage OpenWrt devices over HTTPS instead of SSH.
endef

define Package/salt-agent-ubus/conffiles
endef

define Build/Compile
endef

define Package/salt-agent-ubus/install
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/salt-agent-ubus.json \
		$(1)/usr/share/rpcd/acl.d/salt-agent-ubus.json
endef

# CONTROL/postinst and CONTROL/postrm are the single source of truth.
# Both build.sh and the SDK Makefile read from the same files.
define Package/salt-agent-ubus/postinst
$(shell cat $(CURDIR)/CONTROL/postinst)
endef

define Package/salt-agent-ubus/postrm
$(shell cat $(CURDIR)/CONTROL/postrm)
endef

$(eval $(call BuildPackage,salt-agent-ubus))
