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

# SPA routing: all routes fall back to index.html
RUN echo 'server { \
    listen 3000; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { try_files $uri $uri/ /index.html; } \
    location /health { return 200 "ok"; add_header Content-Type text/plain; } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
