#!/usr/bin/env bash
# TP7 : vérifie que le serveur distant répond et renvoie la bonne version.
set -euo pipefail

: "${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST manquant}"
: "${DEPLOY_SERVER_PORT:?DEPLOY_SERVER_PORT manquant}"
: "${RELEASE_VERSION:?RELEASE_VERSION manquant}"

URL="http://${DEPLOY_SSH_HOST}:${DEPLOY_SERVER_PORT}/version"
echo "Test de connexion externe: ${URL}"

BODY="$(curl -fsS --retry 5 --retry-delay 3 --retry-connrefused "${URL}")"
echo "Réponse: ${BODY}"

REMOTE_VERSION="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' <<<"${BODY}")"
echo "Version distante: ${REMOTE_VERSION}"
echo "Version attendue: ${RELEASE_VERSION}"

if [ "${REMOTE_VERSION}" != "${RELEASE_VERSION}" ]; then
    echo "Échec: version incorrecte" >&2
    exit 1
fi

echo "Vérification distante OK."
