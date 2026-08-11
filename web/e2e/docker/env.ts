/**
 * Port/project budget for the isolated e2e stack — the one place these numbers live, so
 * playwright.config.ts, global-setup.ts and global-teardown.ts cannot disagree about them.
 *
 * Chosen to sit clear of both the dev stack (:8080 caddy, :5432 postgres — see CLAUDE.md) and
 * the other things already running on this machine (:8000 is VS Code — never use it; the dev
 * stack's own auxiliary ports are 8010/5199/5201/8011/5202). 8180/55440 are unrelated to any
 * of those and comfortably above the well-known range.
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// `web/package.json` sets `"type": "module"`, so these .ts files run as ESM under
// Playwright's loader and have no `__dirname` — derive it from `import.meta.url` instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** Compose project name. Namespaces containers, the network, and the two named volumes
 *  below, so `-p kindred-e2e ... down -v` cannot reach anything the dev stack owns. */
export const E2E_PROJECT = 'kindred-e2e'

/** Host port for Caddy (dev stack uses 8080). */
export const E2E_HTTP_PORT = 8180
/** Host port for Postgres, published only so this file could debug into it if needed
 *  (dev stack uses 5432). */
export const E2E_POSTGRES_PORT = 55440

export const E2E_BASE_URL = `http://localhost:${E2E_HTTP_PORT}`

/** web/e2e/docker -> web/e2e -> web -> repo root. */
export const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
export const DEPLOY_DIR = path.join(REPO_ROOT, 'deploy')
export const ENV_FILE = path.join(DEPLOY_DIR, '.env.e2e')
export const COMPOSE_BASE = path.join(DEPLOY_DIR, 'docker-compose.yml')
export const COMPOSE_OVERRIDE = path.join(DEPLOY_DIR, 'docker-compose.e2e.yml')

export const SEED_DEMO_SCRIPT = path.join(REPO_ROOT, 'server', 'scripts', 'seed_demo.py')

/** Seeded on first boot by the app itself (app/core/seed.py), forced-change on first login. */
export const SEED_ADMIN_USERNAME = 'admin'
export const SEED_ADMIN_PASSWORD = 'admin'

/** Demo users created by scripts/seed_demo.py, all sharing DEMO_PASSWORD there. */
export const DEMO_PASSWORD = 'kindred-demo'
export const JOIN_INVITE_TOKEN = 'demo-join-the-jiangs'
