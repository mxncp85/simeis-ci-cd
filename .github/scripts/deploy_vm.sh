#!/usr/bin/env bash
# TP7 : déploie le paquet .deb sur la VM via SSH (scp + apt install).
set -euo pipefail

: "${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST manquant}"
: "${DEPLOY_SSH_PRIVATE_KEY:?DEPLOY_SSH_PRIVATE_KEY manquant}"
: "${DEB_PATH:?DEB_PATH manquant}"
: "${RELEASE_VERSION:?RELEASE_VERSION manquant}"
: "${PKG_NAME:?PKG_NAME manquant}"
: "${DEPLOY_SERVER_PORT:?DEPLOY_SERVER_PORT manquant}"

DEPLOY_SSH_USER="${DEPLOY_SSH_USER:-student}"
DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22222}"

if [ ! -f "$DEB_PATH" ]; then
    echo "Paquet introuvable: $DEB_PATH" >&2
    exit 1
fi

DEB_FILE="$(basename "$DEB_PATH")"
SSH_OPTS=(-p "$DEPLOY_SSH_PORT" -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes)

mkdir -p ~/.ssh
chmod 700 ~/.ssh
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > ~/.ssh/deploy_key
chmod 600 ~/.ssh/deploy_key
ssh-keyscan -p "$DEPLOY_SSH_PORT" "$DEPLOY_SSH_HOST" >> ~/.ssh/known_hosts 2>/dev/null

echo "Copie du paquet vers ${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}:/tmp/${DEB_FILE}"
scp "${SSH_OPTS[@]}" "$DEB_PATH" "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}:/tmp/${DEB_FILE}"

echo "Installation sur la VM et vérification locale du service"
ssh "${SSH_OPTS[@]}" "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}" bash -s <<EOF
set -euo pipefail
sudo DEBIAN_FRONTEND=noninteractive apt install -y "/tmp/${DEB_FILE}"
INSTALLED="\$(dpkg-query -W -f='\${Version}' ${PKG_NAME})"
echo "Version paquet installée: \${INSTALLED}"
test "\${INSTALLED}" = "${RELEASE_VERSION}-1"
systemctl is-active --quiet simeis-server
curl -fsS "http://127.0.0.1:${DEPLOY_SERVER_PORT}/version"
rm -f "/tmp/${DEB_FILE}"
EOF

echo "Déploiement ${RELEASE_VERSION} sur la VM terminé."
