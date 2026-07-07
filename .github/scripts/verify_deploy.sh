#!/usr/bin/env bash
# TP7 : vérifie que le serveur distant répond et renvoie la bonne version.
set -euo pipefail

# Variables injectées par le workflow release-publish.yml.
: "${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST manquant}"
: "${DEPLOY_SERVER_PORT:?DEPLOY_SERVER_PORT manquant}"
: "${RELEASE_VERSION:?RELEASE_VERSION manquant}"

# Endpoint public exposé par le service déployé.
URL="http://${DEPLOY_SSH_HOST}:${DEPLOY_SERVER_PORT}/version"
echo "Test de connexion externe: ${URL}"

# Requête HTTP avec retries pour tolérer un démarrage lent juste après le déploiement.
BODY="$(curl -fsS --retry 5 --retry-delay 3 --retry-connrefused "${URL}")"
echo "Réponse: ${BODY}"

# Extrait le champ JSON "version" de la réponse /version.
REMOTE_VERSION="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' <<<"${BODY}")"
echo "Version distante: ${REMOTE_VERSION}"
echo "Version attendue: ${RELEASE_VERSION}"

# Échec de la CI si la version distante ne correspond pas à la release en cours.
if [ "${REMOTE_VERSION}" != "${RELEASE_VERSION}" ]; then
    echo "Échec: version incorrecte" >&2
    exit 1
fi

# Succès : la VM sert bien la version attendue.
echo "Vérification distante OK."
