#!/bin/sh
# Render the configuration, make sure a certificate exists, then hand over to nginx.
set -e

CERT_DIR=/etc/nginx/certs
PUBLIC_HTTPS_PORT="${SNOWTH_HTTPS_PORT:-8443}"
TLS_HOSTS="${SNOWTH_TLS_HOSTS:-localhost,127.0.0.1}"
export PUBLIC_HTTPS_PORT

envsubst '${PUBLIC_HTTPS_PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# A self-signed certificate, generated once and kept in a volume. Browsers will warn: it
# encrypts the session cookie against a passive listener, it does not prove who answers.
# Replace both files with a certificate signed by your own CA (or Let's Encrypt) to get rid
# of the warning -- nginx reads the same two paths.
if [ ! -f "$CERT_DIR/server.crt" ]; then
  mkdir -p "$CERT_DIR"
  san=""
  for host in $(echo "$TLS_HOSTS" | tr ',' ' '); do
    case "$host" in
      *[!0-9.]*|*:*) san="$san,DNS:$host" ;;          # a name
      *)             san="$san,IP:$host" ;;           # an IPv4 address
    esac
  done
  primary=$(echo "$TLS_HOSTS" | cut -d, -f1)
  echo "generating a self-signed certificate for $TLS_HOSTS"
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.crt" -days 3650 \
    -subj "/CN=$primary" -addext "subjectAltName=${san#,}" 2>/dev/null
  chmod 600 "$CERT_DIR/server.key"
else
  echo "certificate already in place"
fi

exec nginx -g "daemon off;"
