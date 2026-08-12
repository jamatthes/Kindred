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
Caddy obtains and renews the certificate automatically once it serves a real hostname on
ports 80/443 — that is what `docker-compose.prod.yml` is for (next section). Behind
Cloudflare, use an origin certificate or keep the proxy in front — see
`plan/architecture.md` > Deployment.

`:8080` over plain HTTP is for local testing only. It works because browsers treat
`http://localhost` as a secure context, so the `Secure` session cookie is still stored. That
exception does not extend to any other host.

## The live stack, alongside the dev stack

`docker-compose.prod.yml` is an override that turns the dev stack into a public one without
disturbing it. Both run on the same machine at once:

```bash
cd deploy

# dev — plain HTTP on :8080, data in ../data/, uses .env
docker compose -f docker-compose.yml up --build -d

# live — HTTPS on 80/443, isolated named volumes, uses .env.prod
docker compose -p kindred-live --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

What the override changes, and why each one matters:

| Change | Reason |
|---|---|
| `caddy` publishes `80:80` + `443:443` | Browsers assume those ports, and ACME HTTP-01 needs 80 reachable |
| `postgres` publishes nothing | Only the `api` container needs it; nothing on a public box should reach it |
| `postgres`/`api` use **named** volumes | The base file bind-mounts `../data/*`, which is *not* namespaced by `-p`. Without this both stacks would write the same database files — the same trap the e2e override avoids |
| `api` reads `.env.prod` | `env_file:` is a fixed path in the base file; `--env-file` does not change it |

`-p kindred-live` is what keeps the containers, network and volumes separate. Tear it down
with the same `-p` and `-f` flags, plus `-v` only if you mean to destroy the live data.

### Reaching it over IPv6

On an IPv6-only public address there is **no port forwarding to configure** — hosts have
real addresses, so a NAT mapping is neither needed nor possible. What is needed is an
explicit inbound **allow** rule on the gateway, because consumer gateways default-deny
unsolicited inbound IPv6. On UniFi (Network 10.x) that is
`Settings > Policy Engine > Policy Table > Create Policy`:

```
Source Zone      External      (Any)
Destination Zone Internal      IP = <server's IPv6>, Port List = 80, 443
Action           Allow
IP Version       IPv6
Protocol         TCP
```

Point the AAAA record at the host's **Public** address, not its Temporary one — Windows
rotates temporary addresses daily and gateway UIs often display that one. On the host:
`netsh interface ipv6 show addresses` and take the entry typed `Public`.

**Do not test reachability from inside the LAN.** Requests to your own public address
commonly loop back locally and succeed regardless of the firewall, which looks like proof
and is not. Test from outside, and read `logs caddy` — `Timeout during connect (likely
firewall problem)` means the gateway is still blocking, while `served key authentication`
means the challenge got through. Caddy backs off on failure (60s doubling to 600s+), so
after fixing the gateway `restart caddy` to retry immediately instead of waiting.

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

## Where the data lives

Two bind mounts under the repo's `data/` directory, relative to this compose file, so the
data follows the checkout and is visible in a file browser:

| Path | Holds |
|---|---|
| `data/postgres/pgdata/` | The Postgres data directory |
| `data/attachments/` | Uploaded profile pictures and check-in photos |

`data/` is gitignored. Caddy's certificate store and config stay as named volumes
(`kindred_caddy_data`, `kindred_caddy_config`) — regenerable infrastructure, nothing you
would open.

Note `PGDATA` points at `pgdata/` *inside* the mount rather than at the mount point itself.
Postgres requires its data directory to be mode `0700` and cannot `chmod` a bind mount's root,
so `initdb` must create the directory itself one level down.

### This is a trade, and it is worth knowing which way

A bind mount gives visibility. It costs durability guarantees that Postgres assumes it has:

- **On Windows or macOS via Docker Desktop**, permissions are synthesized and `chown`/`chmod`
  are ignored. `initdb` may fail outright with `could not change permissions of directory`.
- **On an SMB/CIFS share** (a mapped network drive, a NAS), it is worse: no reliable file
  locking, and `fsync` that can return before data is on disk. Postgres's crash-safety
  depends on both. A stack that appears to work can still corrupt on an unclean shutdown.
- **Performance** is markedly worse than a named volume in every case.

A named volume has none of these problems because it is a real Linux filesystem inside
Docker's VM. If Postgres will not start, or you start seeing corruption, revert:

```yaml
# deploy/docker-compose.yml — postgres service
volumes:
  - pgdata:/var/lib/postgresql/data
# ...and restore the `pgdata:` entry under the top-level `volumes:` key,
# and delete the PGDATA environment variable.
```

Either way, **the durable answer for anything you care about is a dump, not a copy of the
data directory** — a directory copied while Postgres is running is not a valid backup.

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

# Attachments (uploads live on disk, not in Postgres). Now a bind mount at data/attachments,
# so this is a plain tar of a directory rather than a volume dance.
tar czf "$BACKUP_DIR/attachments-$STAMP.tar.gz" -C /srv/kindred/data/attachments .

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
