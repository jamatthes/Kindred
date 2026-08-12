/**
 * The app shell: nav rail + main + side-panel slot on desktop, bottom tabs + full-bleed
 * main + bottom sheet on mobile. The composition of the top bar is the canonical one from
 * `plan/design-system.md` and the approved mockups in `design-preview/`: wordmark, trip
 * name, stage chip, centred search, bell, family presence stack, primary action.
 *
 * Controls whose feature has not shipped yet are rendered and disabled with a title saying
 * which milestone brings them. That is deliberate: the layout is the thing being verified
 * in M0, and a control that looks live but does nothing is worse than one that says so.
 */

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './apiClient'
import { useSession } from './session'
import { useNavigate } from './router'
import { useSocketStatus } from './socket'
import { IdentityBadge } from '../design/IdentityBadge'
import { familyColor } from '../design/familyColor'
import type { AppRoute } from './router'
import type { PresenceSnapshot, ThemePref, TripStage } from './types'
import './shell.css'

const STAGE_LABEL: Record<TripStage, string> = {
  planning: 'Planning',
  holiday: 'Holiday',
  end: 'Trip finished',
}

/** Nav destinations. `ready` flips to true as each feature lands. */
const NAV = [
  { key: 'home', label: 'Home', ready: true, to: { name: 'home' } as const },
  { key: 'map', label: 'Map', ready: false, arrives: 'the map & suggestions feature' },
  { key: 'polls', label: 'Polls', ready: true, to: { name: 'polls' } as const },
  { key: 'itinerary', label: 'Itinerary', ready: false, arrives: 'the itinerary feature' },
  { key: 'families', label: 'Families', ready: true, to: { name: 'families' } as const },
] as const

function Icon({ name }: { name: string }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    'aria-hidden': true,
  } as const
  switch (name) {
    case 'home':
      return (
        <svg {...common}>
          <path d="M3 11l9-7 9 7" />
          <path d="M5 10v10h14V10" />
        </svg>
      )
    case 'map':
      return (
        <svg {...common}>
          <path d="M9 20l-6-2V4l6 2 6-2 6 2v14l-6-2-6 2z" />
          <path d="M9 6v14M15 4v14" />
        </svg>
      )
    case 'polls':
      return (
        <svg {...common}>
          <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
        </svg>
      )
    case 'itinerary':
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="17" rx="2" />
          <path d="M8 2v4M16 2v4M3 9h18" />
        </svg>
      )
    case 'families':
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3.5" />
          <path d="M2.5 20c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5" />
          <circle cx="17.5" cy="9.5" r="2.7" />
          <path d="M16 15.2c2.6.2 4.7 1.8 5.5 4.3" />
        </svg>
      )
    case 'admin':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.5-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.5-1a7 7 0 0 0 2 1.2L10 21h4l.4-2.6a7 7 0 0 0 2-1.2l2.5 1 2-3.4-2-1.6c.06-.4.1-.8.1-1.2z" />
        </svg>
      )
    case 'bell':
      return (
        <svg {...common}>
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
      )
    case 'plus':
      return (
        <svg {...common} strokeWidth={2.6}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      )
    case 'sun':
      return (
        <svg {...common} width={15} height={15}>
          <circle cx="12" cy="12" r="4.5" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
        </svg>
      )
    case 'moon':
      return (
        <svg {...common} width={15} height={15}>
          <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
        </svg>
      )
    default:
      return (
        <svg {...common} width={15} height={15}>
          <rect x="3" y="4" width="18" height="13" rx="2" />
          <path d="M8 20h8" />
        </svg>
      )
  }
}

function ThemeControl() {
  const { themePref, setThemePref, themeError } = useSession()
  const options: Array<{ value: ThemePref; label: string; icon: string }> = [
    { value: 'light', label: 'Light theme', icon: 'sun' },
    { value: 'dark', label: 'Dark theme', icon: 'moon' },
    { value: 'system', label: 'Match my system', icon: 'system' },
  ]
  return (
    <div
      className="theme-control"
      role="group"
      aria-label="Theme"
      title={themeError ?? 'Theme'}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={themePref === option.value ? 'is-on' : undefined}
          aria-pressed={themePref === option.value}
          aria-label={option.label}
          title={option.label}
          onClick={() => void setThemePref(option.value)}
        >
          <Icon name={option.icon} />
        </button>
      ))}
    </div>
  )
}

/**
 * One avatar per family. Until `families` ships, `auth/me` returns `family: null` for
 * everyone but the seeded admin, so this renders the viewer alone — correct, and it grows
 * into the full stack without a rewrite once families exist.
 */
function PresenceStack({ online }: { online: boolean }) {
  const { user } = useSession()
  if (!user) return null
  const initial = (user.family?.name ?? user.display_name).slice(0, 1).toUpperCase()
  return (
    <div className="presence-stack" aria-label="Who is online">
      {/* One avatar per family; until the full stack arrives with presence fan-out this is
          the viewer's own, which is correct rather than a placeholder. */}
      <IdentityBadge
        initials={initial}
        familyColor={familyColor(user.family)}
        size={32}
        offline={!online}
        name={`${user.family?.name ?? user.display_name} — ${online ? 'online' : 'offline'}`}
      />
    </div>
  )
}

function usePresence(enabled: boolean): string[] {
  const [ids, setIds] = useState<string[]>([])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    api
      .get<PresenceSnapshot>('/presence')
      .then((snapshot) => {
        if (!cancelled) setIds(snapshot.online_user_ids)
      })
      .catch(() => {
        // Presence is decoration, not data: a failure here must never break the shell.
      })
    return () => {
      cancelled = true
    }
  }, [enabled])
  return ids
}

export type ShellProps = {
  children: ReactNode
  /** Desktop right-hand panel; features fill it. Empty in M0. */
  sidePanel?: ReactNode
  activeNav?: string
}

export function Shell({ children, sidePanel, activeNav = 'home' }: ShellProps) {
  const { user } = useSession()
  const navigate = useNavigate()
  const socketStatus = useSocketStatus(Boolean(user) && user?.must_change_password === false)
  usePresence(Boolean(user))

  const stage = user?.trip?.stage ?? 'planning'
  const canSeeAdmin = Boolean(user?.is_owner || user?.is_organiser)
  const online = socketStatus === 'open'

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="rail__logo" aria-hidden="true">
          K
        </div>
        {NAV.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`rail__btn${activeNav === item.key ? ' is-active' : ''}`}
            disabled={!item.ready}
            aria-current={activeNav === item.key ? 'page' : undefined}
            aria-label={item.label}
            title={item.ready ? item.label : `${item.label} — arrives with ${item.arrives}`}
            onClick={() => {
              if ('to' in item) navigate(item.to as AppRoute)
            }}
          >
            <Icon name={item.key} />
          </button>
        ))}
        <div className="rail__spacer" />
        {/* AC-1: the entry exists for the owner and for organisers, and for nobody else.
            Hiding it is a courtesy — every endpoint behind it is guarded server-side, and
            someone typing the URL gets the access screen rather than a broken page. */}
        {canSeeAdmin ? (
          <button
            type="button"
            className={`rail__btn${activeNav === 'admin' ? ' is-active' : ''}`}
            aria-label="Admin console"
            aria-current={activeNav === 'admin' ? 'page' : undefined}
            title="Admin console"
            onClick={() => navigate({ name: 'admin' })}
          >
            <Icon name="admin" />
          </button>
        ) : null}
        <button
          type="button"
          className="rail__btn"
          aria-label="Your profile"
          title={user?.display_name}
          aria-current={activeNav === 'profile' ? 'page' : undefined}
          onClick={() => navigate({ name: 'profile' })}
        >
          {/* The same badge component the member lists and the map use — one person, one
              rendering, everywhere. */}
          <IdentityBadge
            initials={user?.initials ?? ''}
            familyColor={familyColor(user?.family)}
            avatarThumbUrl={user?.avatar_thumb_url}
            size={32}
            name={user?.display_name}
          />
        </button>
      </nav>

      <div className="shell__main">
        <header className="topbar">
          <span className="topbar__wordmark">Kindred</span>
          <span className="topbar__trip">{user?.trip?.name ?? 'No trip yet'}</span>
          <span className={`stage-chip stage-chip--${stage}`}>{STAGE_LABEL[stage]}</span>
          <div className="topbar__grow" />
          <input
            className="topbar__search"
            placeholder="Search places or people"
            disabled
            title="Search arrives with the map & suggestions feature"
          />
          <div className="topbar__grow" />
          <ThemeControl />
          <button
            type="button"
            className="icon-btn"
            disabled
            title="Notifications arrive with the notifications feature"
          >
            <Icon name="bell" />
          </button>
          <PresenceStack online={online} />
          <button
            type="button"
            className="k-btn k-btn--primary"
            disabled
            title="Suggesting a place arrives with the map & suggestions feature"
          >
            <Icon name="plus" />
            Suggest a place
          </button>
        </header>

        <div className="workspace">
          <main className="workspace__main">{children}</main>
          {/* The 38% half of the split, laid out from M0 so features drop in without a
              layout rewrite. Like the timeline slot, it says what it is for rather than
              rendering a blank rectangle. */}
          <aside className="side-panel" aria-label="Details">
            {sidePanel ?? (
              <p className="side-panel__empty">
                Select something on the map or in a list and its details appear here.
              </p>
            )}
          </aside>
        </div>

        <div className="timeline-slot">
          The trip timeline appears here once the itinerary feature lands.
        </div>

        <nav className="tabbar" aria-label="Main">
          {NAV.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`tabbar__tab${activeNav === item.key ? ' is-active' : ''}`}
              disabled={!item.ready}
              aria-current={activeNav === item.key ? 'page' : undefined}
              title={item.ready ? item.label : `${item.label} — arrives with ${item.arrives}`}
              onClick={() => {
                if ('to' in item) navigate(item.to as AppRoute)
              }}
            >
              <Icon name={item.key} />
              {item.label}
            </button>
          ))}
          {canSeeAdmin ? (
            <button
              type="button"
              className={`tabbar__tab${activeNav === 'admin' ? ' is-active' : ''}`}
              aria-current={activeNav === 'admin' ? 'page' : undefined}
              title="Admin console"
              onClick={() => navigate({ name: 'admin' })}
            >
              <Icon name="admin" />
              Admin
            </button>
          ) : null}
        </nav>
      </div>

      {stage === 'end' ? (
        // Persistent, not a toast: this is information that has to stay visible, and the
        // controls it explains the absence of are gone for as long as it is here.
        <div className="archive-banner" role="status">
          This trip has finished — everything is read-only.
        </div>
      ) : null}

      {socketStatus === 'reconnecting' ? (
        <div className="reconnecting" role="status">
          <span className="k-spinner" aria-hidden="true" />
          Reconnecting…
        </div>
      ) : null}
    </div>
  )
}
