include $(TOPDIR)/rules.mk

PKG_NAME:=salt-openwrt
PKG_VERSION:=0.1.0
PKG_RELEASE:=1

PKG_MAINTAINER:=Christian Prior-Mamulyan <cprior@gmail.com>
PKG_LICENSE:=Apache-2.0
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/salt-openwrt
  SECTION:=admin
  CATEGORY:=Administration
  TITLE:=Salt agent configuration for OpenWrt
  PKGARCH:=all
endef

define Package/salt-openwrt/description
  UCI config file controlling Salt extension behavior (mode, enabled).
  Shared by salt-agent-ubus and salt-agent-ssh transport packages.
endef

define Package/salt-openwrt/conffiles
/etc/config/salt-openwrt
endef

define Build/Compile
endef

define Package/salt-openwrt/install
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/salt-openwrt \
		$(1)/etc/config/salt-openwrt
endef

$(eval $(call BuildPackage,salt-openwrt))
