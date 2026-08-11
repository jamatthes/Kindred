/**
 * Tears down the isolated e2e stack: `compose ... down -v` removes the containers, the
 * project's own network, and the two named volumes docker-compose.e2e.yml declares
 * (kindred_e2e_pgdata, kindred_e2e_attachments) — nothing that belongs to the dev stack.
 *
 * Best-effort: if global-setup.ts threw before `compose up` ever ran (e.g. writing
 * deploy/.env.e2e failed), there is no stack to remove and `down` on a project that was
 * never created is a harmless no-op, not an error worth failing the run over.
 */
import { execFileSync } from 'node:child_process'
import { COMPOSE_BASE, COMPOSE_OVERRIDE, DEPLOY_DIR, ENV_FILE, E2E_PROJECT } from './docker/env'

export default async function globalTeardown(): Promise<void> {
  console.log(`[e2e] docker compose -p ${E2E_PROJECT} down -v`)
  try {
    execFileSync(
      'docker',
      ['compose', '-p', E2E_PROJECT, '--env-file', ENV_FILE, '-f', COMPOSE_BASE, '-f', COMPOSE_OVERRIDE, 'down', '-v'],
      { cwd: DEPLOY_DIR, stdio: 'inherit' },
    )
  } catch (cause) {
    console.warn('[e2e] teardown: `compose down -v` failed (stack may not have come up):', cause)
  }
}
