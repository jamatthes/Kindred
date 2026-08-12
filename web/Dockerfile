# Kindred web image: builds the SPA and bakes it into the Caddy image that serves it.
#
# There is no separate "web" service at runtime — Caddy *is* the web service. It serves
# `dist/` as static files and reverse-proxies `/api` and `/ws` to the API, so the browser
# sees one origin and the session cookie is same-origin without any CORS involved.
#
# Build context is `web/` (see deploy/docker-compose.yml). The Caddyfile lives here rather
# than in `deploy/` because it is part of this image and a COPY cannot reach outside the
# build context. It is copied rather than bind-mounted: Docker Desktop cannot bind-mount a file
# from an SMB/UNC share, which fails with "not a directory" on any host whose checkout lives
# on a network drive. Since the SPA bundle is baked into this same image, a proxy change
# already costs a rebuild — the bind mount bought nothing and cost portability.

# ---------------------------------------------------------------------------- build ------
FROM node:26-alpine AS builder

WORKDIR /app

# Copy manifests first so the dependency layer is cached until they actually change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# The browser Maps key, baked into the static bundle at build time -- Vite only inlines
# `import.meta.env.VITE_*` values that exist when it runs, not read at container start.
# Passed through from deploy/docker-compose.yml's `build.args` (itself from deploy/.env),
# and empty by default so an unconfigured key still produces a working build:
# GoogleMapProvider and MapSuggestionsScreen already degrade to FakeMapProvider when this is
# unset (see their own comments). Whenever GOOGLE_MAPS_BROWSER_KEY changes in deploy/.env,
# this image must be rebuilt -- `docker compose up -d` alone will not pick it up, only
# `--build` does, because the value is compiled into the JS, not read at runtime.
ARG VITE_GOOGLE_MAPS_BROWSER_KEY=""
ENV VITE_GOOGLE_MAPS_BROWSER_KEY=${VITE_GOOGLE_MAPS_BROWSER_KEY}

# `npm run build` is `tsc -b && vite build`: a type error fails the image build rather than
# shipping a bundle that does not typecheck.
RUN npm run build

# --------------------------------------------------------------------------- serve -------
FROM caddy:2-alpine AS runtime

COPY --from=builder /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8080
