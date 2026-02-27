#!/bin/bash
# Build .ipk packages without the OpenWrt buildroot.
#
# Creates a minimal ipk (gzipped tar with control.tar.gz + data.tar.gz)
# that can be installed on OpenWrt via: opkg install <file>.ipk
#
# Usage: ./build.sh <package-name>
# Example: ./build.sh openwrt-salt-agent

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_NAME="${1:?Usage: $0 <package-name>}"
PKG_DIR="${SCRIPT_DIR}/packages/${PKG_NAME}"
BUILD_DIR="${SCRIPT_DIR}/build"
WORK_DIR="${BUILD_DIR}/.work/${PKG_NAME}"

if [ ! -d "${PKG_DIR}" ]; then
    echo "Error: package directory not found: ${PKG_DIR}" >&2
    exit 1
fi

if [ ! -f "${PKG_DIR}/CONTROL/control" ]; then
    echo "Error: CONTROL/control not found in ${PKG_DIR}" >&2
    exit 1
fi

# Read version from CONTROL/control
VERSION=$(grep "^Version:" "${PKG_DIR}/CONTROL/control" | cut -d' ' -f2)
ARCH=$(grep "^Architecture:" "${PKG_DIR}/CONTROL/control" | cut -d' ' -f2)
IPK_FILE="${BUILD_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.ipk"

echo "Building ${PKG_NAME} ${VERSION} (${ARCH})"

# Clean working directory
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}/control" "${WORK_DIR}/data"

# Assemble control archive
cp "${PKG_DIR}/CONTROL/control" "${WORK_DIR}/control/"
for script in postinst prerm postrm preinst conffiles; do
    if [ -f "${PKG_DIR}/CONTROL/${script}" ]; then
        cp "${PKG_DIR}/CONTROL/${script}" "${WORK_DIR}/control/"
        chmod 755 "${WORK_DIR}/control/${script}"
    fi
done

# Assemble data archive from files/
# files/ mirrors the target filesystem layout (e.g. files/usr/share/...)
if [ -d "${PKG_DIR}/files" ]; then
    cp -a "${PKG_DIR}/files/"* "${WORK_DIR}/data/" 2>/dev/null || true
fi

# Create inner tarballs (gnu format, same as OpenWrt ipkg-build)
( cd "${WORK_DIR}/control" && tar --format=gnu --numeric-owner --sort=name -cf - . | gzip -n > "${WORK_DIR}/control.tar.gz" )
( cd "${WORK_DIR}/data"    && tar --format=gnu --numeric-owner --sort=name -cf - . | gzip -n > "${WORK_DIR}/data.tar.gz" )

# debian-binary version marker (must be exactly "2.0\n", no CRLF)
printf '2.0\n' > "${WORK_DIR}/debian-binary"

# Assemble ipk as gzipped tar (NOT ar -- OpenWrt ipkg-build uses tar)
# Order must be: ./debian-binary ./data.tar.gz ./control.tar.gz
mkdir -p "${BUILD_DIR}"
rm -f "${IPK_FILE}"
( cd "${WORK_DIR}" && tar --format=gnu --numeric-owner --sort=name -cf - \
    ./debian-binary ./data.tar.gz ./control.tar.gz | gzip -n > "${IPK_FILE}" )

# Clean up
rm -rf "${WORK_DIR}"

echo "Built: ${IPK_FILE}"
echo ""
echo "Install on target:"
echo "  scp ${IPK_FILE} root@<host>:/tmp/"
echo "  ssh root@<host> 'opkg install /tmp/$(basename "${IPK_FILE}")'"
