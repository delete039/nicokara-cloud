#!/usr/bin/env bash
set -Eeuo pipefail

# SSH-panel bootstrap: download the pinned package and run its verified deployer.
BASE_URL="${NICOKARA_RELEASE_BASE_URL:-https://raw.githubusercontent.com/delete039/nicokara-cloud/main/release}"
ARCHIVE="nicokara-cloud-v0.3.0-alpha.3-3bc9458-20261002-002328.tar.gz"
DEPLOY="deploy-nicokara-cloud-v0.3.0-alpha.3-3bc9458-20261002-002328.sh"
CHECKSUM="${ARCHIVE}.sha256"
WORK_DIR="$(mktemp -d /tmp/nicokara-deploy.XXXXXX)"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

command -v curl >/dev/null || { echo "错误：缺少 curl" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "错误：缺少 sha256sum" >&2; exit 1; }

for file in "$ARCHIVE" "$DEPLOY" "$CHECKSUM"; do
  curl --fail --location --silent --show-error "$BASE_URL/$file" -o "$WORK_DIR/$file"
done

cd -- "$WORK_DIR"
sha256sum -c "$CHECKSUM"
chmod 700 "$DEPLOY"
exec "$WORK_DIR/$DEPLOY" "${1:-https://www.nicokara.icu}"
