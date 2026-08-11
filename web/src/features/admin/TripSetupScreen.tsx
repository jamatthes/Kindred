/**
 * AC-0 — the owner's trip setup screen.
 *
 * Reached only through foundation's `next_step: "setup_trip"`, which is the owner's state
 * between changing the seeded password and naming the trip. Outside the app shell on
 * purpose: there is no trip to put in the header yet, and every nav destination would be
 * empty.
 *
 * Abandoning it writes nothing. The gate is derived from `setup_complete`, not from a
 * one-shot redirect, so the next login lands here again with nothing half-written.
 */

import { useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { Banner, Skeleton } from '../../app/ui/primitives'
import type { TripAdmin } from '../../app/types'
import { adminApi } from './api'
import { TripForm } from './TripForm'
import './admin.css'

export function TripSetupScreen() {
  const { logout, refresh } = useSession()
  const [trip, setTrip] = useState<TripAdmin | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    adminApi
      .readTrip()
      .then(setTrip)
      .catch((cause) =>
        setError(cause instanceof ApiError ? cause.message : 'Could not load the trip.'),
      )
  }, [])

  return (
    <div className="auth-screen">
      <div className="auth-card auth-card--wide">
        <div className="auth-wordmark">Kindred</div>
        <h1 className="auth-title">Set up your trip</h1>
        <p className="auth-sub">
          Name it and pick its timezone — you can invite families and decide the dates next.
        </p>

        {error ? <Banner tone="error">{error}</Banner> : null}

        {trip === null && error === null ? (
          <>
            <Skeleton height="var(--field-height)" />
            <div style={{ height: 'var(--space-3)' }} />
            <Skeleton height="var(--field-height)" />
          </>
        ) : null}

        {trip !== null ? (
          <TripForm
            trip={trip}
            submitLabel="Create trip"
            datesOptionalHint
            onSaved={(saved) => {
              setTrip(saved)
              // `setup_complete` flips server-side, so `next_step` becomes `app` and the
              // shell routes to home with the name in the header. Re-reading the session is
              // how the client learns that — it never decides the gate itself.
              void refresh()
            }}
          />
        ) : null}

        <p className="auth-foot">
          {/* This screen carries its own log-out: the nav rail that normally holds one is
              not rendered here. */}
          <button type="button" className="auth-linkbtn" onClick={() => void logout()}>
            Log out
          </button>
        </p>
      </div>
    </div>
  )
}
