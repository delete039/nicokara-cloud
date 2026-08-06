#!/usr/bin/env bash

set -Eeuo pipefail

RELEASE_ID="20260805-172138"
ARCHIVE_NAME="nicokara-cloud-v0.2.0-20260805-172138.tar.gz"
ARCHIVE_SHA256="114409294aa72c3cf93a389129b576dc60df71d539ee6ccdb8c3dce280f4fa85"
APP_ROOT="/data/nicokara"
ARCHIVE="/data/$ARCHIVE_NAME"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
CURRENT_LINK="$APP_ROOT/current"
SHARED_ENV="$APP_ROOT/shared/nicokara.env"
SWITCHED=false
OLD_RELEASE=""

rollback() {
  local exit_code=$?
  if [[ "$SWITCHED" == "true" && -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
    echo "Health check failed. Rolling back to $OLD_RELEASE" >&2
    ln -sfn "$OLD_RELEASE" "$CURRENT_LINK"
    systemctl restart nicokara-backend nicokara-frontend || true
  fi
  exit "$exit_code"
}

trap rollback ERR

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

for command_name in sha256sum tar python3 node curl systemctl sed rm; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Archive not found: $ARCHIVE" >&2
  exit 1
fi

printf '%s  %s\n' "$ARCHIVE_SHA256" "$ARCHIVE" | sha256sum -c -

if [[ ! -f "$SHARED_ENV" ]]; then
  echo "Existing server environment file not found: $SHARED_ENV" >&2
  exit 1
fi

if ! systemctl cat nicokara-backend >/dev/null 2>&1 || \
   ! systemctl cat nicokara-frontend >/dev/null 2>&1; then
  echo "Existing nicokara systemd services were not found." >&2
  exit 1
fi

OLD_RELEASE="$(readlink -f "$CURRENT_LINK")"
if [[ -z "$OLD_RELEASE" || ! -d "$OLD_RELEASE" ]]; then
  echo "Current release link is invalid: $CURRENT_LINK" >&2
  exit 1
fi

ADMIN_TOKEN="$(sed -n 's/^NICOKARA_ADMIN_TOKEN=//p' "$SHARED_ENV" | tail -n 1)"
if [[ -z "$ADMIN_TOKEN" ]]; then
  ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  if grep -q '^NICOKARA_ADMIN_TOKEN=' "$SHARED_ENV"; then
    sed -i "s|^NICOKARA_ADMIN_TOKEN=.*$|NICOKARA_ADMIN_TOKEN=$ADMIN_TOKEN|" "$SHARED_ENV"
  else
    printf '\nNICOKARA_ADMIN_TOKEN=%s\n' "$ADMIN_TOKEN" >> "$SHARED_ENV"
  fi
fi

if ! grep -q '^NICOKARA_WORKER_HEARTBEAT_INTERVAL_SECONDS=' "$SHARED_ENV"; then
  printf 'NICOKARA_WORKER_HEARTBEAT_INTERVAL_SECONDS=5\n' >> "$SHARED_ENV"
fi
chmod 600 "$SHARED_ENV"

mkdir -p "$RELEASE_DIR"
if find "$RELEASE_DIR" -mindepth 1 -print -quit | grep -q .; then
  if [[ "$(readlink -f "$CURRENT_LINK")" == "$RELEASE_DIR" ]]; then
    echo "Release is already active: $RELEASE_DIR"
    exit 0
  fi
  echo "Removing an incomplete previous attempt: $RELEASE_DIR"
  rm -rf -- "$RELEASE_DIR"
  mkdir -p "$RELEASE_DIR"
fi

echo "Extracting $ARCHIVE_NAME"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR" --strip-components=1

for required_file in \
  "$RELEASE_DIR/frontend/server.js" \
  "$RELEASE_DIR/backend/pyproject.toml" \
  "$RELEASE_DIR/backend/app/main.py"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Deployment package is missing: $required_file" >&2
    exit 1
  fi
done

echo "Installing backend dependencies. This can take several minutes."
python3 -m venv "$RELEASE_DIR/backend/.venv"
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install --upgrade pip
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install \
  -e "$RELEASE_DIR/backend[ai]"

chown -R www-data:www-data "$RELEASE_DIR"

echo "Switching current release from $OLD_RELEASE to $RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
SWITCHED=true

systemctl restart nicokara-backend nicokara-frontend

BACKEND_READY=false
for _ in {1..60}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null; then
    BACKEND_READY=true
    break
  fi
  sleep 1
done
if [[ "$BACKEND_READY" != "true" ]]; then
  journalctl -u nicokara-backend -n 100 --no-pager >&2 || true
  false
fi

FRONTEND_READY=false
for _ in {1..30}; do
  if curl --fail --silent --head http://127.0.0.1:3000/ >/dev/null; then
    FRONTEND_READY=true
    break
  fi
  sleep 1
done
if [[ "$FRONTEND_READY" != "true" ]]; then
  journalctl -u nicokara-frontend -n 100 --no-pager >&2 || true
  false
fi

curl --fail --silent --show-error \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://127.0.0.1:8000/api/v1/admin/queue-health >/dev/null

SWITCHED=false
trap - ERR

echo "Deployment complete."
echo "Previous release: $OLD_RELEASE"
echo "Current release:  $RELEASE_DIR"
echo "Admin page:       https://www.nicokara.icu/admin"
echo "Admin token:      $ADMIN_TOKEN"
