# Kindred web image: builds the SPA and bakes it into the Caddy image that serves it.
#
# There is no separate "web" service at runtime — Caddy *is* the web service. It serves
# `dist/` as static files and reverse-proxies `/api` and `/ws` to the API, so the browser
# sees one origin and the session cookie is same-origin without any CORS involved.
#
# Build context is `web/` (see deploy/docker-compose.yml). The Caddyfile is bind-mounted
# rather than copied, so an operator can adjust it without a rebuild.

# ---------------------------------------------------------------------------- build ------
FROM node:26-alpine AS builder

WORKDIR /app

# Copy manifests first so the dependency layer is cached until they actually change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `npm run build` is `tsc -b && vite build`: a type error fails the image build rather than
# shipping a bundle that does not typecheck.
RUN npm run build

# --------------------------------------------------------------------------- serve -------
FROM caddy:2-alpine AS runtime

COPY --from=builder /app/dist /srv

EXPOSE 8080
