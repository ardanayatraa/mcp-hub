#!/usr/bin/env bash
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo 'Image builds run in GitHub Actions only'; exit 1; }
[[ "${DEPLOY_COMMIT:-}" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit'; exit 1; }
[[ -d "${RELEASE_OUTPUT:-}" ]] || { echo 'Release output directory missing'; exit 1; }
schema="$(python3 -c 'import sys; from pathlib import Path; sys.path.insert(0,"deploy/aapanel"); from docker_deploy import target_schema; print(target_schema(Path(".")))')"
printf '{"commit":"%s"}\n' "$DEPLOY_COMMIT" > frontend/dist/release-version.json
for service in backend edge; do
  docker build --platform linux/amd64 --file "deploy/aapanel/Dockerfile.$service" \
    --build-arg "DEPLOY_COMMIT=$DEPLOY_COMMIT" --build-arg "SCHEMA_REVISION=$schema" \
    --tag "mcp-hub-ci-$service:$DEPLOY_COMMIT" .
done
docker save "mcp-hub-ci-backend:$DEPLOY_COMMIT" "mcp-hub-ci-edge:$DEPLOY_COMMIT" \
  | gzip -1 > "$RELEASE_OUTPUT/images.tar.gz"
python3 deploy/aapanel/build_release.py --commit "$DEPLOY_COMMIT" --output "$RELEASE_OUTPUT/source.tar.gz"
sha256sum "$RELEASE_OUTPUT/"*.tar.gz
