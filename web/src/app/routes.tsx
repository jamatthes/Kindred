/**
 * Top-level routing.
 *
 * Two things happen here, and keeping them apart is the point:
 *
 * 1. **The gate.** `routeFor` in `session.ts` turns the server's `next_step` into one of five
 *    top-level screens. The client is told the answer, never the precedence, so the forced
 *    password change and both setup screens cannot be navigated around — they are not routes
 *    the user is *sent to*, they are the only thing that renders until the server says
 *    otherwise.
 * 2. **The route.** Within the app, `router.ts` says which screen the URL asks for.
 *
 * The URL never overrides the gate. `/join/<token>` is the one exception and it is not one
 * really: it is a public screen for someone with no session at all, so there is no gate to
 * override.
 */

import { useSession } from './session'
import { useRoute } from './router'
import { Shell } from './shell'
import { Button, Skeleton } from './ui/primitives'
import LoginScreen from '../features/auth/LoginScreen'
import ChangePasswordScreen from '../features/auth/ChangePasswordScreen'
import { FamiliesScreen } from '../features/families/FamiliesScreen'
import { FamilySetupScreen } from '../features/families/FamilySetupScreen'
import { JoinScreen } from '../features/families/JoinScreen'
import { ProfileScreen } from '../features/families/ProfileScreen'
import { Home } from '../features/home/Home'
import { Styleguide } from '../charts/Styleguide'

/** Structural load: the shell's shape, not a spinner. */
function ShellSkeleton() {
  return (
    <div className="home" aria-busy="true">
      <Skeleton height="var(--text-heading)" width="60%" />
      <div style={{ height: 'var(--space-3)' }} />
      <Skeleton height="var(--text-body)" width="80%" />
      <div style={{ height: 'var(--space-4)' }} />
      <Skeleton height="var(--space-6)" />
    </div>
  )
}

/**
 * `next_step: "setup_trip"` — the owner has not set the trip up. The screen belongs to
 * `admin-console` (AC-0), which owns every write to `trips`; the gate that leads here is
 * foundation's and already works. Until that feature lands this says so plainly, because a
 * blank screen would look like a bug and a redirect would put someone somewhere the server
 * will not let them act.
 */
function TripSetupPlaceholder() {
  const { logout } = useSession()
  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-wordmark">Kindred</div>
        <h1 className="auth-title">Set up your trip</h1>
        <p className="auth-sub">
          This screen arrives with the admin console. Everything else is ready and waiting for
          it.
        </p>
        <Button block variant="secondary" onClick={() => void logout()}>
          Log out
        </Button>
      </div>
    </div>
  )
}

function NotFound({ path }: { path: string }) {
  return (
    <div className="home">
      <h1 className="home__title">Nothing here</h1>
      <p className="home__sub">
        <code>{path}</code> is not a page in Kindred.
      </p>
    </div>
  )
}

/** Inside the shell: the destinations a member can actually reach. */
function AppRoutes() {
  const route = useRoute()

  switch (route.name) {
    case 'families':
      return (
        <Shell activeNav="families">
          <FamiliesScreen selectedId={route.familyId} />
        </Shell>
      )
    case 'profile':
      return (
        <Shell activeNav="profile">
          <ProfileScreen />
        </Shell>
      )
    case 'not-found':
      return (
        <Shell>
          <NotFound path={route.path} />
        </Shell>
      )
    // `join` and `setup-family` are handled above the gate; reaching them here means the
    // session moved on (they finished, or logged in), so home is the honest answer.
    default:
      return (
        <Shell activeNav="home">
          <Home />
        </Shell>
      )
  }
}

export function Routes() {
  const { route: gate } = useSession()
  const url = useRoute()

  // Public, and deliberately checked before the gate: a visitor holding an invite link has
  // no session, and sending them to the login screen would strand them with a link they
  // cannot use and no way to register.
  if (url.name === 'join') return <JoinScreen token={url.token} />

  switch (gate) {
    case 'loading':
      return <ShellSkeleton />
    case 'login':
      return <LoginScreen />
    case 'password-change':
      return <ChangePasswordScreen />
    case 'setup-trip':
      return <TripSetupPlaceholder />
    case 'setup-family':
      return <FamilySetupScreen />
    case 'app':
      // Internal, unlinked gallery (DS-13) — behind the authenticated branch, gated by
      // path rather than a router entry (it is a developer surface, not a destination).
      if (window.location.pathname === '/styleguide') {
        return <Styleguide />
      }
      return <AppRoutes />
  }
}
