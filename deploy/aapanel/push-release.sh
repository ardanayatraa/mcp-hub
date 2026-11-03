#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "${DEPLOY_COMMIT:-}" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit'; exit 1; }
[[ "${AAPANEL_SSH_HOST:-}" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'Configure AAPANEL_SSH_HOST'; exit 1; }
[[ "${AAPANEL_SSH_USER:-}" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo 'Configure AAPANEL_SSH_USER'; exit 1; }
[[ "${AAPANEL_SSH_PORT:-}" =~ ^[0-9]{1,5}$ ]] || { echo 'Invalid SSH port'; exit 1; }
(( 10#$AAPANEL_SSH_PORT >= 1 && 10#$AAPANEL_SSH_PORT <= 65535 )) || { echo 'Invalid SSH port'; exit 1; }
[[ -n "${AAPANEL_SSH_PRIVATE_KEY:-}" && -n "${AAPANEL_SSH_KNOWN_HOSTS:-}" ]] || { echo 'Configure deployment SSH secrets'; exit 1; }
[[ -d "${RUNNER_TEMP:-}" ]] || { echo 'Runner temporary directory missing'; exit 1; }
[[ -f "${RELEASE_INPUT:-}/source.tar.gz" && -f "$RELEASE_INPUT/images.tar.gz" ]] || { echo 'Tested prebuilt artifacts missing'; exit 1; }

key="$RUNNER_TEMP/aapanel-deploy-key"
hosts="$RUNNER_TEMP/aapanel-known-hosts"
archive="$RELEASE_INPUT/source.tar.gz"
images="$RELEASE_INPUT/images.tar.gz"
trap 'rm -f -- "$key" "$hosts"' EXIT
printf '%s\n' "$AAPANEL_SSH_PRIVATE_KEY" > "$key"
printf '%s\n' "$AAPANEL_SSH_KNOWN_HOSTS" > "$hosts"
chmod 600 "$key" "$hosts"
checksum="$(sha256sum "$archive" | cut -d ' ' -f1)"
image_checksum="$(sha256sum "$images" | cut -d ' ' -f1)"
[[ "$checksum" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid release digest'; exit 1; }
[[ "$image_checksum" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid image digest'; exit 1; }

options=(-i "$key" -p "$AAPANEL_SSH_PORT" -o BatchMode=yes -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$hosts" -o ConnectTimeout=15
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3)
destination="$AAPANEL_SSH_USER@$AAPANEL_SSH_HOST"
status="$(ssh "${options[@]}" "$destination" status)"
printf '%s' "$status" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("protocol") == "prebuilt-v1", "Install the reviewed prebuilt controller first"'
# The forced-command protocol receives client-side values already restricted to hexadecimal.
# shellcheck disable=SC2029
ssh "${options[@]}" "$destination" "upload $DEPLOY_COMMIT" < "$archive"
# shellcheck disable=SC2029
ssh "${options[@]}" "$destination" "upload-images $DEPLOY_COMMIT $image_checksum" < "$images"
# shellcheck disable=SC2029
ssh "${options[@]}" "$destination" "deploy-images $DEPLOY_COMMIT $checksum $image_checksum"
