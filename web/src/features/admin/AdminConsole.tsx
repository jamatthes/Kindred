/**
 * The admin console (AC-1 to AC-13).
 *
 * A **sectioned page**, not tabs and not a modal: its content is configuration, which the
 * reader compares and returns to, and `plan/design-system.md` reserves overlays for
 * temporary interactions. One readable column with a sticky section index on desktop; the
 * index becomes a jump menu on mobile.
 *
 * This is the one screen where the 62/38 map split does not apply, because there is no map
 * dataset here.
 *
 * Which sections render is decided by `auth/me`'s role flags — but only what to *render*.
 * Every endpoint behind them is guarded server-side, and the Organisers section's writes are
 * refused for an organiser whatever this file does.
 */

import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { socket } from '../../app/socket'
import { Banner, Button, Skeleton, TextField } from '../../app/ui/primitives'
import type {
  AdminMember,
  CategorySetting,
  Family,
  GoogleStatus,
  InstanceSettings,
  Organiser,
  StageTransition,
  Stats,
  TripAdmin,
} from '../../app/types'
import { adminApi } from './api'
import { GoogleSection } from './GoogleSection'
import { MembersSection } from './MembersSection'
import { OrganisersSection } from './OrganisersSection'
import { StageSection } from './StageSection'
import { TripForm } from './TripForm'
import { VotingModesSection } from './VotingModesSection'
import './admin.css'

const SECTIONS: { id: string; label: string; ownerOnly?: boolean }[] = [
  { id: 'section-trip', label: 'Trip' },
  { id: 'section-stage', label: 'Stage' },
  { id: 'section-voting', label: 'Voting modes' },
  { id: 'section-members', label: 'Families and members' },
  { id: 'section-instance', label: 'Instance' },
  { id: 'section-google', label: 'Google APIs' },
  { id: 'section-stats', label: 'Stats' },
  { id: 'section-organisers', label: 'Organisers', ownerOnly: true },
]

/** Everything the console reads, loaded together so the page settles once. */
type ConsoleData = {
  trip: TripAdmin
  history: StageTransition[]
  categories: CategorySetting[]
  families: Family[]
  members: AdminMember[]
  organisers: Organiser[]
  settings: InstanceSettings
  google: GoogleStatus
  stats: Stats
}

export function AdminConsole() {
  const { user, refresh } = useSession()
  const [data, setData] = useState<ConsoleData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const isOwner = Boolean(user?.is_owner)

  const load = useCallback(async (search = '') => {
    try {
      const [trip, history, categories, overview, organisers, settings, google, stats] =
        await Promise.all([
          adminApi.readTrip(),
          adminApi.stageHistory(),
          adminApi.categorySettings(),
          adminApi.overview(search),
          adminApi.organisers(),
          adminApi.settings(),
          adminApi.googleStatus(),
          adminApi.stats(),
        ])
      setData({
        trip,
        history,
        categories,
        families: overview.families,
        members: overview.members,
        organisers,
        settings,
        google,
        stats,
      })
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The console could not load.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // The search filters server-side, because the same box filters both tables and the server
  // is the thing that knows how a family name relates to a member.
  useEffect(() => {
    const timer = setTimeout(() => {
      adminApi
        .overview(query)
        .then((overview) =>
          setData((current) =>
            current
              ? { ...current, families: overview.families, members: overview.members }
              : current,
          ),
        )
        .catch(() => {
          /* the tables keep what they have; the error banner is for actions, not typing */
        })
    }, 200)
    return () => clearTimeout(timer)
  }, [query])

  // Another admin's change lands here without a reload: this console is the one screen where
  // two people are most likely to be working at once.
  useEffect(() => {
    const off = [
      socket.subscribe('stage.changed', () => void load(query)),
      socket.subscribe('trip.updated', () => void load(query)),
      socket.subscribe('organiser.appointed', () => void load(query)),
      socket.subscribe('organiser.demoted', () => void load(query)),
      socket.subscribe('member.removed', () => void load(query)),
    ]
    return () => off.forEach((unsubscribe) => unsubscribe())
  }, [load, query])

  if (error !== null && data === null) {
    return (
      <div className="admin">
        <Banner tone="error">{error}</Banner>
      </div>
    )
  }

  if (data === null) {
    return (
      <div className="admin" aria-busy="true">
        <Skeleton height="var(--text-heading)" width="40%" />
        <div className="admin__spacer" />
        <Skeleton height="var(--space-6)" />
        <div className="admin__spacer" />
        <Skeleton height="var(--space-6)" />
      </div>
    )
  }

  const sections = SECTIONS.filter((section) => !section.ownerOnly || isOwner)

  return (
    <div className="admin">
      <header className="admin__head">
        <h1 className="admin__title">Admin console</h1>
        <p className="admin__hint">
          {isOwner ? 'Owner' : 'Organiser'} · changes here affect everyone on the trip.
        </p>
      </header>

      {error ? <Banner tone="error">{error}</Banner> : null}

      <div className="admin__body">
        <nav className="admin__index" aria-label="Sections">
          {sections.map((section) => (
            <a key={section.id} href={`#${section.id}`}>
              {section.label}
            </a>
          ))}
        </nav>

        <div className="admin__column">
          <section className="admin__section" id="section-trip" aria-labelledby="trip-heading">
            <h2 className="admin__section-title" id="trip-heading">
              Trip
            </h2>
            <TripForm
              trip={data.trip}
              submitLabel="Save"
              onSaved={(trip) => {
                setData((current) => (current ? { ...current, trip } : current))
                // The name is in the app header, which comes from `auth/me`.
                void refresh()
              }}
            />
          </section>

          <StageSection
            trip={data.trip}
            history={data.history}
            onChanged={() => {
              void load(query)
              void refresh()
            }}
          />

          <VotingModesSection
            settings={data.categories}
            onSaved={(categories) =>
              setData((current) => (current ? { ...current, categories } : current))
            }
          />

          <MembersSection
            families={data.families}
            members={data.members}
            query={query}
            onQueryChange={setQuery}
            onChanged={() => void load(query)}
          />

          <InstanceSection
            settings={data.settings}
            canEdit={isOwner}
            onSaved={(settings) =>
              setData((current) => (current ? { ...current, settings } : current))
            }
          />

          <GoogleSection
            status={data.google}
            onChecked={(google) =>
              setData((current) => (current ? { ...current, google } : current))
            }
          />

          <StatsSection stats={data.stats} />

          {isOwner ? (
            <OrganisersSection
              organisers={data.organisers}
              members={data.members}
              onChanged={() => void load(query)}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** Section 5 — instance settings. Read by organisers, written by the owner. */
function InstanceSection({
  settings,
  canEdit,
  onSaved,
}: {
  settings: InstanceSettings
  canEdit: boolean
  onSaved: (next: InstanceSettings) => void
}) {
  const [name, setName] = useState(settings.instance_name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      onSaved(await adminApi.patchSettings({ instance_name: name.trim() }))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'It did not save.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="admin__section"
      id="section-instance"
      aria-labelledby="instance-heading"
    >
      <h2 className="admin__section-title" id="instance-heading">
        Instance
      </h2>
      {canEdit ? null : (
        <p className="admin__hint">
          These are platform settings rather than trip settings, so only the owner can change
          them.
        </p>
      )}

      {error ? <Banner tone="error">{error}</Banner> : null}

      <TextField
        label="Instance name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        disabled={!canEdit || busy}
        hint="Shown on the login screen and on invite previews."
      />

      <fieldset className="admin__fieldset">
        <legend>Who can register</legend>
        <label className="admin__radio">
          <input type="radio" name="registration" checked readOnly />
          Invite only
        </label>
        {/* Visible rather than hidden, so the roadmap is legible (AC-9). */}
        <label className="admin__radio is-disabled">
          <input type="radio" name="registration" disabled />
          Anyone with a link <span className="admin__muted">— not available in this version</span>
        </label>
        <label className="admin__radio is-disabled">
          <input type="radio" name="registration" disabled />
          Open registration <span className="admin__muted">— not available in this version</span>
        </label>
      </fieldset>

      {canEdit ? (
        <div className="admin__actions">
          <Button
            busy={busy}
            disabled={name.trim() === settings.instance_name}
            onClick={() => void save()}
          >
            Save
          </Button>
        </div>
      ) : null}
    </section>
  )
}

/** Section 7 — stats. Plain numbers: no comparison, no trend, so no chart. */
function StatsSection({ stats }: { stats: Stats }) {
  const cells: [string, number][] = [
    ['Families', stats.families],
    ['Members', stats.members],
    ['Invites open', stats.invites_open],
    ['Polls open', stats.polls_open],
    ['Polls closed', stats.polls_closed],
    ['Suggestions proposed', stats.suggestions_by_status.proposed],
    ['Suggestions approved', stats.suggestions_by_status.approved],
    ['Scheduled', stats.suggestions_by_status.scheduled],
    ['Comments', stats.comments],
    ['Itinerary items', stats.itinerary_items],
    ['Check-ins', stats.checkins],
    ['Unread notifications', stats.notifications_unread],
  ]
  return (
    <section className="admin__section" id="section-stats" aria-labelledby="stats-heading">
      <h2 className="admin__section-title" id="stats-heading">
        Stats
      </h2>
      <dl className="stats">
        {cells.map(([label, value]) => (
          <div className="stats__cell" key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="admin__hint">
        Counts for features that have not shipped yet read zero rather than hiding.
      </p>
    </section>
  )
}
