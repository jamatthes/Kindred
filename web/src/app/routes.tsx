/**
 * Top-level routing.
 *
 * There is no route table yet because M0 has one destination. What matters here is the
 * *gate*: which of the three top-level screens the session allows. `routeFor` in
 * `session.ts` owns that decision, and this file only renders its answer — which is why
 * the forced password change cannot be navigated around. It is not a route the user is
 * sent to; it is the only thing that renders until the server says otherwise.
 *
 * Feature routing arrives with the first feature that has more than one screen.
 */

import { useState } from 'react'
import { useSession } from './session'
import { Shell } from './shell'
import { BottomSheet } from './BottomSheet'
import { Button, Skeleton } from './ui/primitives'
import LoginScreen from '../features/auth/LoginScreen'
import ChangePasswordScreen from '../features/auth/ChangePasswordScreen'

const STAGE_BLURB: Record<string, string> = {
  planning: 'Suggest places, vote, and settle the plan.',
  holiday: "You're away — check in and see what's next.",
  end: 'This trip has finished — everything is read-only.',
}

function Home() {
  const { user } = useSession()
  const [sheetOpen, setSheetOpen] = useState(false)
  const trip = user?.trip ?? null

  const details = (
    <>
      <div className="home__row">
        <span className="label">Stage</span>
        <span>{trip ? STAGE_BLURB[trip.stage] : '—'}</span>
      </div>
      <div className="home__row">
        <span className="label">Dates</span>
        <span>
          {trip?.start_date && trip?.end_date
            ? `${trip.start_date} to ${trip.end_date}`
            : 'Not decided yet'}
        </span>
      </div>
      <div className="home__row">
        <span className="label">Timezone</span>
        <span>{trip?.timezone ?? '—'}</span>
      </div>
      <div className="home__row">
        <span className="label">Your family</span>
        <span>{user?.family?.name ?? 'Not on a family yet — an invite adds you to one.'}</span>
      </div>
    </>
  )

  return (
    <div className="home">
      <h1 className="home__title">{trip?.name ?? 'Your trip'}</h1>
      <p className="home__sub">
        {trip
          ? STAGE_BLURB[trip.stage]
          : 'No trip has been created yet. The organiser sets one up in the admin console.'}
      </p>

      <div className="home__card">{details}</div>

      {/* The sheet is the mobile side panel. Kept reachable in M0 so the pattern is
          verifiable before a feature depends on it. */}
      <div className="home__card">
        <Button variant="secondary" onClick={() => setSheetOpen(true)}>
          Open trip details
        </Button>
      </div>

      <BottomSheet open={sheetOpen} title="Trip details" onClose={() => setSheetOpen(false)}>
        {details}
      </BottomSheet>
    </div>
  )
}

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

export function Routes() {
  const { route } = useSession()

  switch (route) {
    case 'loading':
      return <ShellSkeleton />
    case 'login':
      return <LoginScreen />
    case 'password-change':
      return <ChangePasswordScreen />
    case 'app':
      return (
        <Shell>
          <Home />
        </Shell>
      )
  }
}
