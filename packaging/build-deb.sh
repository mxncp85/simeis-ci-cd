#!/usr/bin/env bash
# Construit un paquet .deb minimal selon le HOWTO Debian (dpkg-deb + fakeroot).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_VERSION="${1:-0.1.3}"
ARCH="${2:-amd64}"
DEB_VERSION="${UPSTREAM_VERSION}-1"

BINARY="${ROOT_DIR}/target/release/simeis-server"
if [ ! -f "$BINARY" ]; then
    echo "Binaire introuvable: $BINARY (lancez d'abord: make release)" >&2
    exit 1
fi

STAGING="${ROOT_DIR}/build/deb/staging"
OUTPUT_DIR="${ROOT_DIR}/build/deb"
PKG_ROOT="${STAGING}/simeis_${DEB_VERSION}_${ARCH}"

rm -rf "${STAGING}"
mkdir -p \
    "${PKG_ROOT}/DEBIAN" \
    "${PKG_ROOT}/usr/bin" \
    "${PKG_ROOT}/usr/share/man/man1" \
    "${PKG_ROOT}/usr/share/doc/simeis" \
    "${PKG_ROOT}/etc/systemd/system"

# data.tar.gz : fichiers installés sur le système cible.
# TP5 : binaire /usr/bin, manuel, service systemd.
install -m 0755 "$BINARY" "${PKG_ROOT}/usr/bin/simeis-server"
install -m 0644 "${ROOT_DIR}/packaging/debian/simeis-server.1" \
    "${PKG_ROOT}/usr/share/man/man1/simeis-server.1"
gzip --best -f "${PKG_ROOT}/usr/share/man/man1/simeis-server.1"
install -m 0644 "${ROOT_DIR}/packaging/debian/simeis-server.service" \
    "${PKG_ROOT}/etc/systemd/system/simeis-server.service"

# Documentation Debian (copyright + changelog).
install -m 0644 "${ROOT_DIR}/packaging/debian/copyright" \
    "${PKG_ROOT}/usr/share/doc/simeis/copyright"
install -m 0644 "${ROOT_DIR}/packaging/debian/changelog" \
    "${PKG_ROOT}/usr/share/doc/simeis/changelog"
install -m 0644 "${ROOT_DIR}/packaging/debian/changelog.Debian" \
    "${PKG_ROOT}/usr/share/doc/simeis/changelog.Debian"
gzip --best -f "${PKG_ROOT}/usr/share/doc/simeis/changelog"
gzip --best -f "${PKG_ROOT}/usr/share/doc/simeis/changelog.Debian"

# control.tar.gz : métadonnées + scripts de maintenance.
cat > "${PKG_ROOT}/DEBIAN/control" <<EOF
Package: simeis
Version: ${DEB_VERSION}
Section: games
Priority: optional
Architecture: ${ARCH}
Maintainer: Simeis & k4os
Depends: cmatrix, systemd
Description: Simeis game server
 Jeu multijoueur par API. Ce paquet installe le binaire serveur,
 la page de manuel et le service systemd associé.
EOF

install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/postinst" "${PKG_ROOT}/DEBIAN/postinst"
install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/prerm" "${PKG_ROOT}/DEBIAN/prerm"
install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/postrm" "${PKG_ROOT}/DEBIAN/postrm"

# Permissions recommandées par le HOWTO.
find "${PKG_ROOT}" -type d -exec chmod 755 {} +

mkdir -p "$OUTPUT_DIR"
# fakeroot : propriétaires root/root dans l'archive.
fakeroot dpkg-deb --build "${PKG_ROOT}" "${OUTPUT_DIR}/simeis_${DEB_VERSION}_${ARCH}.deb"

echo "Paquet créé: ${OUTPUT_DIR}/simeis_${DEB_VERSION}_${ARCH}.deb"
