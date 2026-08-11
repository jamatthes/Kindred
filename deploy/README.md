# Deploying Kindred

Three containers: `postgres`, `api` (uvicorn/FastAPI) and `caddy` (serves the built SPA and
reverse-proxies `/api` and `/ws`). One `.env`. One command.

## First run

```bash
cd deploy
cp .env.example .env

# 1. A real secret. The API refuses to boot while SECRET_KEY is unset or the placeholder.
openssl rand -hex 32          # paste into SECRET_KEY

# 2. A real database password, in POSTGRES_PASSWORD.
#    Change it BEFORE the first `up` — it is only applied when the volume is initialised.

# 3. The address Caddy serves on.
#    Production: KINDRED_SITE_ADDRESS=kindred.example.org  (Caddy provisions TLS itself)
#    Local test: KINDRED_SITE_ADDRESS=:8080

docker compose -f docker-compose.yml up --build -d
```

Then open the site and log in as `admin` / `admin`. You are forced to change the password
before anything else works; the new password survives restarts.

On boot the API waits for Postgres (retrying for up to 60s), applies Alembic migrations, and
runs the idempotent seed — one platform admin and one trip in `planning`. It only starts
accepting traffic after all of that. `GET /api/v1/health` returns `{"db": "ok"}` when it is
ready; the compose healthcheck watches that endpoint.

### HTTPS is not optional in production

Browser geolocation, PWA install, service workers and Web Push all require a secure context.
Set `KINDRED_SITE_ADDRESS` to a hostname, uncomment the `80:80` and `443:443` port mappings
in `docker-compose.yml`, and Caddy obtains and renews the certificate automatically. Behind
Cloudflare, use an origin certificate or keep the proxy in front — see
`plan/architecture.md` > Deployment.

`:8080` over plain HTTP is for local testing only. It works because browsers treat
`http://localhost` as a secure context, so the `Secure` session cookie is still stored. That
exception does not extend to any other host.

## Ports

| Variable | Default | What |
|---|---|---|
| `KINDRED_HTTP_PORT` | `8080` | Host port published for Caddy |
| `KINDRED_POSTGRES_PORT` | `5432` | Host port for Postgres, for host-side alembic/pytest |

The `api` container is **not** published. Nothing reaches it except through Caddy, which is
the point — one origin, so the session cookie is same-origin and CORS stays out of it.

Drop the `postgres` `ports:` block entirely on a server that does not run the test suite.

## `DATABASE_URL` in two places

`.env`'s `DATABASE_URL` is for **host-side** tooling (`alembic`, `pytest`) and normally points
at `localhost`. The `api` container needs the compose service name instead, so
`docker-compose.yml` derives its own value from `POSTGRES_USER` / `POSTGRES_PASSWORD` /
`POSTGRES_DB` and overrides it. One `.env` serves both, and a stale host in `.env` cannot
quietly break the container.

## Comments in `.env`

Keep every comment on its own line. Compose strips a trailing comment only when the value is
non-empty: `GOOGLE_MAPS_BROWSER_KEY=       # a note` sets the key to the literal string
`# a note`, not to empty, and the app would then believe a key is configured. `.env.example`
is written to avoid this; keep that shape.

## Verifying a clean install without destroying your data

The first-run path is only really tested from empty volumes, and you do not want to wipe a
working instance to test it. Give the trial run its own compose project, and it gets its own
volumes and its own containers alongside the real ones:

```bash
cd deploy
cp .env.example .env.verify          # gitignored; set SECRET_KEY, a password,
                                     # KINDRED_HTTP_PORT=8099, KINDRED_POSTGRES_PORT=55432

cat > docker-compose.verify.yml <<'YAML'
services:
  api:
    env_file: .env.verify
YAML

docker compose -p kindred-verify --env-file .env.verify \
  -f docker-compose.yml -f docker-compose.verify.yml up --build -d
```

`-p kindred-verify` is what isolates it: volumes become `kindred-verify_pgdata` and so on.
The override is needed because the `api` service's `env_file:` is a fixed path inside the
compose file, which `--env-file` does not change. Tear the whole thing down with
`... -p kindred-verify ... down -v`, then delete the two throwaway files.

## Backups

Nightly `pg_dump` plus the attachments volume. Both matter — a database without its
attachments restores a trip with broken photos.

```bash
#!/bin/sh
# /etc/cron.daily/kindred-backup
set -eu
BACKUP_DIR=/srv/backups/kindred
STAMP=$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"

# Database
docker compose -f /srv/kindred/deploy/docker-compose.yml exec -T postgres \
  pg_dump -U kindred -d kindred --format=custom \
  > "$BACKUP_DIR/kindred-$STAMP.dump"

# Attachments volume (uploads live on a volume, not in Postgres)
docker run --rm \
  -v kindred_attachments:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine:3.20 tar czf "/backup/attachments-$STAMP.tar.gz" -C /data .

# Keep 30 days
find "$BACKUP_DIR" -type f -mtime +30 -delete
```

Restore:

```bash
docker compose exec -T postgres pg_restore -U kindred -d kindred --clean --if-exists \
  < kindred-YYYYMMDD.dump
```

Test a restore into a scratch database occasionally. An untested backup is a hope, not a
backup.

## Google Cloud Console guardrails

From `plan/architecture.md`. Do these when you add the keys, not after the first bill.

1. **Two separate keys, never one.**
   - `GOOGLE_MAPS_BROWSER_KEY` — Maps JS and Places, restricted by **HTTP referrer** to your
     domain. It is visible in the page source; the referrer restriction is what makes that
     acceptable.
   - `GOOGLE_MAPS_SERVER_KEY` — Geocoding, Distance Matrix, Directions, restricted by **IP**
     to the server's address. It never reaches a browser.
2. **Restrict each key by API**, not only by referrer/IP, to the specific APIs listed above.
3. **Quota caps at the free-tier thresholds** on every enabled API, so an accident stops
   rather than bills.
4. **A billing alert** at a low figure, plus a budget. The caps are the mechanism; the alert
   is how you find out the mechanism fired.
5. Leave both keys blank until you need maps. The app starts and runs without them, degrading
   only the features that use them.

Kindred is built to keep usage near zero regardless: everything external is called
server-side and cached in Postgres (geocodes forever, distances until a pin moves, routes
until the itinerary changes). Places details are the one exception, re-fetched live on
card-open because Google's terms forbid persisting them.

## Operating

```bash
docker compose -f deploy/docker-compose.yml ps           # state and health
docker compose -f deploy/docker-compose.yml logs -f api  # startup, migrations, seed
docker compose -f deploy/docker-compose.yml up -d --build   # deploy a new build
docker compose -f deploy/docker-compose.yml down         # stop; volumes are kept
```

`down` without `-v` preserves the data. `down -v` destroys the database, the attachments and
Caddy's certificates — including the changed admin password.

## If it will not start

| Symptom | Cause |
|---|---|
| `api` exits immediately, log names `SECRET_KEY` | Still unset or still the placeholder |
| `api` restarts, log shows connection retries then exit | Postgres unreachable for 60s — check `postgres` health |
| Login page loads, API calls 502 | `api` unhealthy; `logs api`. A failed migration is fatal by design |
| Password not accepted after a redeploy | The volume was destroyed (`down -v`); the seed recreated `admin`/`admin` |
| Cookie not stored in the browser | Serving plain HTTP on a hostname other than `localhost` |
