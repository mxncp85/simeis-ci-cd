#!/usr/bin/env bash
# Construit un paquet .deb minimal selon le HOWTO Debian (dpkg-deb + fakeroot).

# -e pour s'arrêter en cas d'erreur
# -u pour s'arrêter en cas d'utilisation d'une variable non définie
# -o pipefail pour s'arrêter en cas d'erreur dans une commande pipée
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Version du paquet, par défaut 0.1.4
UPSTREAM_VERSION="${1:-0.1.4}"
# Architecture du paquet, par défaut amd64
ARCH="${2:-amd64}"
# Nom du paquet, par défaut simeis-ci-cd
PKG_NAME="${PKG_NAME:-simeis-ci-cd}"
# Version du paquet, par défaut x.x.x-1
DEB_VERSION="${UPSTREAM_VERSION}-1"

# Chemin du binaire, par défaut target/release/simeis-server
BINARY="${ROOT_DIR}/target/release/simeis-server"
# Si le binaire n'existe pas, afficher un message d'erreur et quitter
if [ ! -f "$BINARY" ]; then
    echo "Binaire introuvable: $BINARY (lancez d'abord: make release)" >&2
    exit 1
fi

# Dossier de staging (espace de travail temporaire), par défaut build/deb/staging
STAGING="${ROOT_DIR}/build/deb/staging"
# Dossier de sortie (résultat final), par défaut build/deb
OUTPUT_DIR="${ROOT_DIR}/build/deb"
# Chemin du paquet, par défaut build/deb/staging/simeis-ci-cd_x.x.x-1_amd64
PKG_ROOT="${STAGING}/${PKG_NAME}_${DEB_VERSION}_${ARCH}"

# Supprimer le dossier de staging s'il existe
rm -rf "${STAGING}"
# Créer les dossiers nécessaires pour le paquet
mkdir -p "${PKG_ROOT}/DEBIAN" \
    "${PKG_ROOT}/usr/bin" \
    "${PKG_ROOT}/usr/share/man/man1" \
    "${PKG_ROOT}/usr/share/doc/${PKG_NAME}" "${PKG_ROOT}/etc/systemd/system"

# Installer le binaire
install -m 0755 "$BINARY" "${PKG_ROOT}/usr/bin/simeis-server"

# Installer le manuel
install -m 0644 "${ROOT_DIR}/packaging/debian/simeis-server.1" \
    "${PKG_ROOT}/usr/share/man/man1/simeis-server.1"

# Comprimer le manuel
gzip --best -f "${PKG_ROOT}/usr/share/man/man1/simeis-server.1"

# Installer le service systemd
install -m 0644 "${ROOT_DIR}/packaging/debian/simeis-server.service" \
    "${PKG_ROOT}/etc/systemd/system/simeis-server.service"

# Documentation Debian (copyright + changelog).
install -m 0644 "${ROOT_DIR}/packaging/debian/copyright" \
    "${PKG_ROOT}/usr/share/doc/${PKG_NAME}/copyright"

# Installer le changelog
install -m 0644 "${ROOT_DIR}/packaging/debian/changelog" \
    "${PKG_ROOT}/usr/share/doc/${PKG_NAME}/changelog"

# Installer le changelog Debian
install -m 0644 "${ROOT_DIR}/packaging/debian/changelog.Debian" \
    "${PKG_ROOT}/usr/share/doc/${PKG_NAME}/changelog.Debian"

# Comprimer le changelog et le changelog Debian
gzip --best -f "${PKG_ROOT}/usr/share/doc/${PKG_NAME}/changelog"
gzip --best -f "${PKG_ROOT}/usr/share/doc/${PKG_NAME}/changelog.Debian"

# Installer le fichier control
# Remplacer les variables dans le fichier control.in par les valeurs correspondantes
sed -e "s/@PKG_NAME@/${PKG_NAME}/" \
    -e "s/@VERSION@/${DEB_VERSION}/" \
    -e "s/@ARCH@/${ARCH}/" \
    "${ROOT_DIR}/packaging/debian/DEBIAN/control.in" > "${PKG_ROOT}/DEBIAN/control"

# Installer les scripts de maintenance
# (install permet de copier les fichiers, et attribuer les permissions)
# postinst : script post-installation
# prerm : script pre-suppression
# postrm : script post-suppression
install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/postinst" "${PKG_ROOT}/DEBIAN/postinst"
install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/prerm" "${PKG_ROOT}/DEBIAN/prerm"
install -m 0755 "${ROOT_DIR}/packaging/debian/DEBIAN/postrm" "${PKG_ROOT}/DEBIAN/postrm"

# Permissions recommandées par le HOWTO.
find "${PKG_ROOT}" -type d -exec chmod 755 {} +

# Créer le dossier de sortie s'il n'existe pas
mkdir -p "$OUTPUT_DIR"

# Construire le paquet
# fakeroot : propriétaires root/root dans l'archive.
fakeroot dpkg-deb --build "${PKG_ROOT}" "${OUTPUT_DIR}/${PKG_NAME}_${DEB_VERSION}_${ARCH}.deb"

# Afficher le résultat
echo "Paquet créé: ${OUTPUT_DIR}/${PKG_NAME}_${DEB_VERSION}_${ARCH}.deb"
