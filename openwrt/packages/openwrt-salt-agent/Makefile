include $(TOPDIR)/rules.mk

PKG_NAME:=openwrt-salt-agent
PKG_VERSION:=0.1.0
PKG_RELEASE:=1

PKG_MAINTAINER:=Christian Prior-Mamulyan <cprior@gmail.com>
PKG_LICENSE:=Apache-2.0
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/openwrt-salt-agent
  SECTION:=admin
  CATEGORY:=Administration
  TITLE:=Salt agent user and ACLs for remote UCI management
  DEPENDS:=+rpcd +uhttpd-mod-ubus
  PKGARCH:=all
endef

define Package/openwrt-salt-agent/description
  Creates an rpcd login for the salt user and installs ACL rules
  granting scoped access to UCI, network, and system ubus objects
  via the JSON-RPC API. Used by the saltext-uci Salt extension to
  manage OpenWrt devices over HTTPS instead of SSH.
endef

define Package/openwrt-salt-agent/conffiles
endef

define Build/Compile
endef

define Package/openwrt-salt-agent/install
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/openwrt-salt-agent.json \
		$(1)/usr/share/rpcd/acl.d/openwrt-salt-agent.json
endef

# CONTROL/postinst and CONTROL/postrm are the single source of truth.
# Both build.sh and the SDK Makefile read from the same files.
define Package/openwrt-salt-agent/postinst
$(shell cat $(CURDIR)/CONTROL/postinst)
endef

define Package/openwrt-salt-agent/postrm
$(shell cat $(CURDIR)/CONTROL/postrm)
endef

$(eval $(call BuildPackage,openwrt-salt-agent))
