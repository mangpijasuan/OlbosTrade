# ── Build stage ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install --legacy-peer-deps

COPY . .
RUN npm run build

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM nginx:1.25-alpine AS runtime

# Copy built React app
COPY --from=builder /app/dist /usr/share/nginx/html

# SPA routing + API proxy so the app works behind Caddy AND when reached directly
# by host IP:port (no domain needed). /api, /ws, /docs are proxied to the backend
# container; everything else falls back to the SPA index.
RUN echo 'server { \
    listen 3000; \
    root /usr/share/nginx/html; \
    index index.html; \
    location /api { proxy_pass http://olbosquant-backend:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $remote_addr; } \
    location /docs { proxy_pass http://olbosquant-backend:8000; } \
    location /openapi.json { proxy_pass http://olbosquant-backend:8000; } \
    location /ws { proxy_pass http://olbosquant-backend:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; } \
    location /health { return 200 "ok"; add_header Content-Type text/plain; } \
    location / { try_files $uri $uri/ /index.html; } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
