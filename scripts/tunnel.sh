#!/usr/bin/env bash
# Public tunnel for the dashboard via Serveo (works through the sandbox
# egress proxy; Pinggy's free tier screens browser traffic, Serveo's
# doesn't). Proxy URL is read from TUNNEL_PROXY_URL in the project .env.
set -u
cd "$(dirname "$0")/.."
PROXY=$(grep -E "^TUNNEL_PROXY_URL=" .env | cut -d= -f2-)
# PROXY looks like http://user:pass@host:port
AUTH_HOST=${PROXY#*://}
USERPASS=${AUTH_HOST%@*}
HOSTPORT=${AUTH_HOST#*@}
HOST=${HOSTPORT%:*}
PORT=${HOSTPORT#*:}
exec ssh -p 443 -R 80:localhost:8600 serveo.net \
  -o "ProxyCommand=socat - PROXY:${HOST}:serveo.net:443,proxyport=${PORT},proxyauth=${USERPASS}" \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=yes
