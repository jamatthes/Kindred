# Kindred e2e harness

Playwright smokes against a real, disposable copy of the whole stack (Postgres + api +
Caddy, built from Docker images — the same three containers `deploy/docker-compose.yml`
runs in production). Chromium only, and deliberately not part of `npm run verify` — verify
stays fast and network-free; this is the thing to run before calling a milestone "verified"
by hand.

## Running it

```bash
cd web
npx playwright install chromium   # first run only, installs the browser binary
npm run e2e
```

That's the whole command. `global-setup.ts` brings up the isolated stack, waits for it to
report healthy, seeds demo data, and hands control to the tests; `global-teardown.ts` tears
it down again — including on failure. Nothing survives between runs and nothing needs
cleaning up by hand. A full run (build + up + seed + four smokes + down) takes a few minutes
on a cold Docker cache and well under a minute once images are cached.

Docker Desktop must be running. Nothing else needs to be started first — in particular, do
**not** start the dev stack (`docker compose -f deploy/docker-compose.yml up`) before running
this; the two are isolated from each other on purpose (see below) but there is no reason to
run both at once.

## Isolation rules — read before adding a smoke that touches the stack

The harness never touches the dev stack you use day to day. Concretely:

| | Dev stack | e2e stack |
|---|---|---|
| Compose project | `kindred` (the `name:` in `deploy/docker-compose.yml`) | `kindred-e2e` |
| Caddy / HTTP | `:8080` | `:8180` |
| Postgres | `:5432` | `:55440` |
| Postgres data | bind mount `data/postgres/` | named volume `kindred_e2e_pgdata` |
| Attachments | bind mount `data/attachments/` | named volume `kindred_e2e_attachments` |
| Env file | `deploy/.env` (yours, hand-written) | `deploy/.env.e2e` (generated fresh every run by `global-setup.ts`, git-ignored) |

The port numbers and project name live in one place, `docker/env.ts` — if you ever need a
different port, change it there, not in three files.

**Why a named volume instead of just a different `-p`:** `docker-compose.yml`'s Postgres and
attachments volumes are *bind mounts* to `../data/postgres` and `../data/attachments` —
paths relative to the compose file, not to the project name. A second compose project with
only `-p kindred-e2e` would still point at those exact host directories, which is precisely
the data corruption `deploy/README.md`'s "Verifying a clean install without destroying your
data" section exists to avoid. `deploy/docker-compose.e2e.yml` overrides both mounts to named
volumes, which *are* namespaced by project — that override is why the isolation actually
holds, not the `-p` flag alone.

If you touch `deploy/docker-compose.e2e.yml`, keep both overrides (env_file **and** the two
volumes) — dropping either one reopens this hole.

`global-teardown.ts` always runs `docker compose -p kindred-e2e ... down -v`, which removes
exactly the containers, network and two volumes above. It never runs `down` without `-v`
(these are throwaway by design — there is nothing in them worth keeping between runs) and it
never touches anything under the `kindred` project name.

## Port budget

Reserved for this harness: **8180** (HTTP) and **55440** (Postgres). Both are ≥8180/55440 as
agreed, clear of the dev stack (8080/5432) and of VS Code's own 8000 on this machine (see
root `CLAUDE.md`). If a future feature's smoke needs a port of its own (a second isolated
stack running concurrently, say), pick the next free ones above 8180/55440 and record them
here rather than reusing these.

## How the stack gets seeded

`server/Dockerfile` does not ship `server/scripts/` (only `app/`, `alembic/`,
`alembic.ini`) — `seed_demo.py` is a development tool, not part of the image. So
`global-setup.ts`:

1. writes `deploy/.env.e2e` with fresh random `SECRET_KEY`/`POSTGRES_PASSWORD`;
2. `docker compose -p kindred-e2e ... up --build -d` — this runs the app's own first-run
   seed (`app/core/seed.py`: the `admin`/`admin` platform admin and one trip) as part of the
   `api` container's normal startup, same as any real first boot;
3. polls `GET /api/v1/health` until `db: "ok"`;
4. `docker compose cp`'s `seed_demo.py` into the running `api` container and runs it there,
   so it executes with the container's own `DATABASE_URL` and installed dependencies — no
   host-side Python/venv needed.

The demo users this produces (`plan`'s reference, unchanged): `admin`/`admin` (forced change
on first login), `alex` / `jibby` / `jas` / `chris` / `stu` all on `kindred-demo`, plus two
outstanding invites — `/join/demo-join-the-jiangs` (join) and `/join/demo-new-family`
(create-family).

## The smokes

Numbered files (`01-`…`04-`) because `playwright.config.ts` sets `workers: 1` and
`fullyParallel: false` — they run in one browser process, in file order, against one shared
stack, and some depend on state an earlier one left behind:

1. **`01-fresh-install.spec.ts`** — `admin`/`admin` through the whole onboarding gate:
   forced password change, then trip setup (seed_demo.py never marks `Trip.setup_complete`,
   so the owner still owes AC-0's screen), landing in the app. Written against the *screens
   the server actually serves* (`next_step` off `GET /auth/me` / the login response), not a
   hardcoded step count — see its own comment for why that matters right now (a
   owner-family-gate change may land soon). This is the one test that changes the admin
   password and flips `setup_complete`; both are permanent for the stack's lifetime, which is
   why it has to run first.
2. **`02-demo-locality.spec.ts`** — logs in as `jibby` and checks a family card that is not
   jibby's own (The Parkers): shows the locality ("Bristol") and the "home address visible to
   them only" caption, never the street address.
3. **`03-join-invite.spec.ts`** — a fresh, unauthenticated browser context registers through
   `/join/demo-join-the-jiangs`, lands in the app, and shows up as a member of The Jiangs.
4. **`04-ws-liveness.spec.ts`** — two open browser contexts (two sessions, two sockets); one
   creates a family, the other — already sitting on the Families screen, never reloaded —
   sees the new card appear. Exercises `/ws`'s `family.created` broadcast landing on a socket
   that did not just handshake, which a request/response test cannot exercise at all.

### What got cut

A presence indicator check ("X is online" reflected across two contexts) was scoped but not
written — foundation's presence model is check-in/live-location driven and would need either
`GET /ws` geolocation mocking or a check-in flow this harness has no other reason to drive
yet, for coverage `04-ws-liveness.spec.ts` already gets more directly and more cheaply
through `family.created`. Add it back once a feature's own smoke needs presence for real
reasons — don't add a smoke to prove infrastructure works in the abstract.

## Adding a smoke

- Put it in `tests/`, numbered to say where it needs to run relative to the others (or
  unprefixed only if it is truly order-independent and does not mutate anything the numbered
  ones assume).
- Prefer `page.getByRole` / `page.getByLabel` over CSS selectors — the app already gives
  every form field an accessible label (`TextField`'s `label` prop) and every nav control an
  `aria-label`; there is no `data-testid` convention in this codebase (checked: `web/src`
  before this harness had none outside test files) and starting one just for e2e would be a
  second, weaker source of truth for what the UI says.
- Constants that describe the seeded/isolated stack (ports, demo usernames, the join token)
  belong in `docker/env.ts`, not copy-pasted into a spec.
- Keep the total smoke count small. A flaky smoke is worse than no smoke — fix it or delete
  it (see the presence cut above for what "delete it" looks like when the fix would cost more
  than the coverage is worth). This suite exists so future milestones get a cheap, repeatable
  verify; a slow or flaky one defeats that on both counts.
- If a smoke needs *another* isolated stack running concurrently with this one (rare — most
  additions are new specs against the same stack), give it its own project name and port pair
  above 8180/55440 and document it in the port budget table above.

## Troubleshooting

- **`npm run e2e` hangs on "waiting for /api/v1/health"** — `docker compose -p kindred-e2e -f
  ../deploy/docker-compose.yml -f ../deploy/docker-compose.e2e.yml --env-file
  ../deploy/.env.e2e logs api` (run from `web/e2e/docker` or adjust the relative paths) shows
  why; most often a build failure upstream, visible in the same `up --build` output
  `global-setup.ts` streams to the console.
- **Leftover containers/volumes after a crashed run** — teardown runs even on failure, but a
  killed process (Ctrl-C mid-run, a machine sleep) can skip it. Clean up by hand with:
  `docker compose -p kindred-e2e -f deploy/docker-compose.yml -f deploy/docker-compose.e2e.yml
  --env-file deploy/.env.e2e down -v` from the repo root. This only ever touches the
  `kindred-e2e` project — safe to run at any time, including while the dev stack is up.
- **Port already in use** — something else on this machine is on 8180 or 55440. Check with
  `netstat -ano | findstr 8180` (Windows) before assuming it is a stale e2e run; if it is a
  stale run, the cleanup command above fixes it.
