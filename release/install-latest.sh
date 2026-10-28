#!/usr/bin/env bash
set -Eeuo pipefail

# SSH-panel bootstrap: download the pinned v4.2 package and run its verified deployer.
# GitHub's contents API avoids networks that replace raw.githubusercontent.com with HTML.
BASE_URL="${NICOKARA_RELEASE_BASE_URL:-https://api.github.com/repos/delete039/nicokara-cloud/contents/release/artifacts/v4.2}"
REF="${NICOKARA_RELEASE_REF:-main}"
ARCHIVE="nicokara-cloud-v4.2-latest.tar.gz"
DEPLOY="deploy-nicokara-cloud-v4.2-latest.sh"
CHECKSUM="${ARCHIVE}.sha256"
WORK_DIR="$(mktemp -d /tmp/nicokara-deploy.XXXXXX)"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

command -v curl >/dev/null || { echo "错误：缺少 curl" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "错误：缺少 sha256sum" >&2; exit 1; }

for file in "$ARCHIVE" "$DEPLOY" "$CHECKSUM"; do
  curl --fail --location --silent --show-error \
    -H 'Accept: application/vnd.github.raw' \
    "$BASE_URL/$file?ref=$REF" -o "$WORK_DIR/$file"
done

cd -- "$WORK_DIR"
sha256sum -c "$CHECKSUM"
chmod 700 "$DEPLOY"
exec "$WORK_DIR/$DEPLOY" "${1:-https://www.nicokara.icu}"
