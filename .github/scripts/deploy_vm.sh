#!/usr/bin/env bash
# TP7 : déploie le paquet .deb sur la VM via SSH (scp + apt install).
set -euo pipefail

# Variables obligatoires injectées par le workflow release-publish.yml.
: "${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST manquant}"
: "${DEPLOY_SSH_PRIVATE_KEY:?DEPLOY_SSH_PRIVATE_KEY manquant}"
: "${DEB_PATH:?DEB_PATH manquant}"
: "${RELEASE_VERSION:?RELEASE_VERSION manquant}"
: "${PKG_NAME:?PKG_NAME manquant}"
: "${DEPLOY_SERVER_PORT:?DEPLOY_SERVER_PORT manquant}"

# Valeurs par défaut si non définies dans les variables du dépôt.
DEPLOY_SSH_USER="${DEPLOY_SSH_USER:-student}"
DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22222}"

# Vérifie que l'artefact .deb existe bien côté runner CI.
if [ ! -f "$DEB_PATH" ]; then
    echo "Paquet introuvable: $DEB_PATH" >&2
    exit 1
fi

DEB_FILE="$(basename "$DEB_PATH")"
REMOTE="${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"

# Options SSH communes :
# - identité forcée (deploy_key)
# - vérification d'hôte activée
# - mode batch (pas de prompt interactif)
# - timeout de connexion
COMMON_OPTS=(-i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20)
SSH_OPTS=(-p "$DEPLOY_SSH_PORT" "${COMMON_OPTS[@]}")
# scp utilise -P (majuscule) pour le port, contrairement à ssh.
SCP_OPTS=(-P "$DEPLOY_SSH_PORT" "${COMMON_OPTS[@]}")

# Prépare ~/.ssh et écrit la clé privée depuis le secret GitHub.
mkdir -p ~/.ssh
chmod 700 ~/.ssh
# Préserver les retours ligne de la clé (secret GitHub).
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" | tr -d '\r' > ~/.ssh/deploy_key
chmod 600 ~/.ssh/deploy_key

# Validation basique de la clé privée (évite de lancer ssh avec une clé invalide).
if ! ssh-keygen -y -f ~/.ssh/deploy_key >/dev/null 2>&1; then
    echo "Clé privée SSH invalide dans DEPLOY_SSH_PRIVATE_KEY." >&2
    exit 1
fi

# Ajoute l'empreinte du serveur à known_hosts pour StrictHostKeyChecking.
ssh-keyscan -p "$DEPLOY_SSH_PORT" "$DEPLOY_SSH_HOST" >> ~/.ssh/known_hosts 2>/dev/null || true

# Test de connectivité/authentification avant de copier le paquet.
# NOTE : Ici sa bug, on n'arrive pas à se connecter à la VM, il faut voir avec les clés.
echo "Test connexion SSH vers ${REMOTE}:${DEPLOY_SSH_PORT}"
if ! ssh "${SSH_OPTS[@]}" "$REMOTE" "echo SSH OK"; then
    echo "Connexion SSH impossible depuis le runner GitHub." >&2
    echo "Vérifiez : clé publique dans ~/.ssh/authorized_keys de ${DEPLOY_SSH_USER}," >&2
    echo "port ${DEPLOY_SSH_PORT} ouvert vers Internet, secret DEPLOY_SSH_PRIVATE_KEY correct." >&2
    exit 1
fi

# Transfert du paquet vers /tmp sur la VM.
echo "Copie du paquet vers ${REMOTE}:/tmp/${DEB_FILE}"
if ! scp "${SCP_OPTS[@]}" "$DEB_PATH" "${REMOTE}:/tmp/${DEB_FILE}"; then
    echo "scp a échoué (droits sur /tmp ou espace disque ?)." >&2
    exit 1
fi

# Installation distante + vérifications post-déploiement :
# - apt install du .deb
# - version installée conforme
# - service systemd actif
# - endpoint /version joignable en local VM
# - nettoyage du fichier temporaire
echo "Installation sur la VM et vérification locale du service"
ssh "${SSH_OPTS[@]}" "$REMOTE" bash -s <<EOF
set -euo pipefail
sudo DEBIAN_FRONTEND=noninteractive apt install -y "/tmp/${DEB_FILE}"
INSTALLED="\$(dpkg-query -W -f='\${Version}' ${PKG_NAME})"
echo "Version paquet installée: \${INSTALLED}"
test "\${INSTALLED}" = "${RELEASE_VERSION}-1"
systemctl is-active --quiet simeis-server
curl -fsS "http://127.0.0.1:${DEPLOY_SERVER_PORT}/version"
rm -f "/tmp/${DEB_FILE}"
EOF

# Message final si tout s'est bien passé.
echo "Déploiement ${RELEASE_VERSION} sur la VM terminé."
