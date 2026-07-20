#!/bin/sh
# OlbosTrade frontend entrypoint.
#
# Writes the nginx config at startup and — when DASH_USER / DASH_PASS are set —
# password-protects the WHOLE app (dashboard + proxied /api) with HTTP Basic Auth.
# This is the access control for direct IP exposure: one browser login covers
# everything reachable on the published port. /health is exempt so the container
# healthcheck still works. If no credentials are set, the app serves open (with a
# loud warning) to preserve local/dev behaviour.
set -e

AUTH_BLOCK=""
if [ -n "$DASH_USER" ] && [ -n "$DASH_PASS" ]; then
    htpasswd -bc /etc/nginx/.htpasswd "$DASH_USER" "$DASH_PASS" >/dev/null 2>&1
    AUTH_BLOCK='auth_basic "OlbosTrade"; auth_basic_user_file /etc/nginx/.htpasswd;'
    echo "[entrypoint] Dashboard auth ENABLED (user: $DASH_USER)"
else
    echo "[entrypoint] WARNING: DASH_USER/DASH_PASS not set — dashboard is OPEN to anyone who can reach this port."
fi

cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;
    ${AUTH_BLOCK}

    # Healthcheck must stay open (container probe has no credentials).
    location = /health { auth_basic off; return 200 "ok"; add_header Content-Type text/plain; }

    location /api         { proxy_pass http://olbostrade-backend:8000; proxy_set_header Host \$host; proxy_set_header X-Forwarded-For \$remote_addr; }
    location /docs        { proxy_pass http://olbostrade-backend:8000; }
    location /openapi.json { proxy_pass http://olbostrade-backend:8000; }
    location /ws {
        proxy_pass http://olbostrade-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    # Hashed build assets (filename changes every build) can cache forever;
    # index.html can't — it's what points browsers at the current hash, so a
    # cached copy silently keeps a tab on an old build after every deploy.
    location ~* \.(js|css|woff2?|png|jpg|jpeg|gif|svg|ico)\$ {
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files \$uri =404;
    }
    location / {
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

exec nginx -g 'daemon off;'
