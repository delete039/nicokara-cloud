#!/usr/bin/env bash

set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 用户执行此脚本。" >&2
  exit 1
fi

PUBLIC_HOST="${1:-}"
LISTEN_PORT="${2:-10018}"

if [[ ! "$PUBLIC_HOST" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "服务器 IP 或域名格式错误: $PUBLIC_HOST" >&2
  echo "用法: $0 服务器IP或域名 [端口]" >&2
  echo "示例: $0 192.0.2.10 10018" >&2
  exit 1
fi

if [[ ! "$LISTEN_PORT" =~ ^[0-9]+$ ]] ||
  ((LISTEN_PORT < 1 || LISTEN_PORT > 65535)); then
  echo "端口必须是 1-65535 之间的整数: $LISTEN_PORT" >&2
  exit 1
fi

NGINX_CONFIG="/etc/nginx/sites-available/nicokara"
ENV_FILE="/data/nicokara/shared/nicokara.env"
BACKUP_DIR="/data/nicokara/backups/nginx-port-$(date +%Y%m%d-%H%M%S)"
PUBLIC_ORIGIN="http://$PUBLIC_HOST:$LISTEN_PORT"

for required_file in "$NGINX_CONFIG" "$ENV_FILE"; do
  if [[ ! -f "$required_file" ]]; then
    echo "缺少配置文件: $required_file" >&2
    echo "请先执行断点启动脚本完成首次服务配置。" >&2
    exit 1
  fi
done

mkdir -p "$BACKUP_DIR"
cp -a "$NGINX_CONFIG" "$BACKUP_DIR/nicokara.nginx.conf"
cp -a "$ENV_FILE" "$BACKUP_DIR/nicokara.env"

NGINX_TEMP="$(mktemp)"
ENV_TEMP="$(mktemp)"
trap 'rm -f "$NGINX_TEMP" "$ENV_TEMP"' EXIT

sed -E \
  -e "s/^([[:space:]]*)listen[[:space:]]+[0-9]+;/\1listen $LISTEN_PORT;/" \
  -e "s/^([[:space:]]*)server_name[[:space:]]+[^;]+;/\1server_name $PUBLIC_HOST;/" \
  "$NGINX_CONFIG" >"$NGINX_TEMP"

sed -E \
  "s|^NICOKARA_ALLOWED_ORIGINS=.*$|NICOKARA_ALLOWED_ORIGINS=$PUBLIC_ORIGIN|" \
  "$ENV_FILE" >"$ENV_TEMP"

cp "$NGINX_TEMP" "$NGINX_CONFIG"
cp "$ENV_TEMP" "$ENV_FILE"
chmod 640 "$ENV_FILE"

if ! nginx -t; then
  echo "Nginx 配置校验失败，正在恢复原配置..." >&2
  cp "$BACKUP_DIR/nicokara.nginx.conf" "$NGINX_CONFIG"
  cp "$BACKUP_DIR/nicokara.env" "$ENV_FILE"
  nginx -t || true
  exit 1
fi

systemctl reload nginx
systemctl restart nicokara-backend

curl --fail --silent --show-error --head \
  "http://127.0.0.1:$LISTEN_PORT/" |
  sed -n '1p'

echo "端口切换完成: $PUBLIC_ORIGIN"
echo "配置备份目录: $BACKUP_DIR"
echo "请确认服务器防火墙和云安全组已放行 TCP $LISTEN_PORT。"
