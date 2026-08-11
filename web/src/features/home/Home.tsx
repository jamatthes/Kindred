/**
 * The home region. Foundation's empty state, moved out of `routes.tsx` now that routing is
 * real and that file has a job of its own.
 *
 * Still deliberately thin: home becomes the map once `map-suggestions` lands. What it must
 * not be is a blank rectangle, so it names the trip, its stage and the viewer's family.
 */

import { useSession } from '../../app/session'
import { useNavigate } from '../../app/router'
import { Button } from '../../app/ui/primitives'

const STAGE_BLURB: Record<string, string> = {
  planning: 'Suggest places, vote, and settle the plan.',
  holiday: "You're away — check in and see what's next.",
  end: 'This trip has finished — everything is read-only.',
}

export function Home() {
  const { user } = useSession()
  const navigate = useNavigate()
  const trip = user?.trip ?? null

  return (
    <div className="home">
      <h1 className="home__title">{trip?.name ?? 'Your trip'}</h1>
      <p className="home__sub">
        {trip
          ? STAGE_BLURB[trip.stage]
          : 'No trip has been created yet. The organiser sets one up in the admin console.'}
      </p>

      <div className="home__card">
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
      </div>

      <div className="home__card">
        <Button variant="secondary" onClick={() => navigate({ name: 'families' })}>
          See the families
        </Button>
      </div>
    </div>
  )
}
