/**
 * Filters, as a dropdown over the map — replaces the permanent chip band the side panel used
 * to carry (`design.md` > "List/table specifics", revised 2026-08-12).
 *
 * The chips themselves are unchanged: same three groups, same multi-select toggle semantics,
 * same shared `suggestionStore`. What changed is that they no longer spend a strip of the
 * screen announcing that nothing is filtered. The trigger carries the active count, so the
 * one fact the old band communicated at rest — "filters are on" — survives at a fraction of
 * the space, and the map keeps the pixels.
 *
 * Closes on outside click and on Escape, and returns focus to the trigger, because a popover
 * that traps the user is worse than the band it replaced.
 */

import { useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useFamilies } from '../families/useFamilies'
import { familyColor } from '../../design/familyColor'
import { hasActiveFilters, suggestionStore, useSuggestionView } from './store'
import type { SuggestionStatus, SuggestionType } from '../../app/types'
import './suggestionsList.css'
import './filterMenu.css'

const TYPE_LABEL: Record<SuggestionType, string> = {
  region: 'Region',
  accommodation: 'Accommodation',
  activity: 'Activity',
  meal: 'Meal',
  other: 'Other',
}

const STATUS_LABEL: Record<SuggestionStatus, string> = {
  proposed: 'Proposed',
  shortlisted: 'Shortlisted',
  approved: 'Approved',
  scheduled: 'Scheduled',
  rejected: 'Rejected',
}

const TYPES: SuggestionType[] = ['region', 'accommodation', 'activity', 'meal', 'other']
const STATUSES: SuggestionStatus[] = ['proposed', 'shortlisted', 'approved', 'scheduled', 'rejected']

export function FilterMenu() {
  const view = useSuggestionView()
  const { families } = useFamilies()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const panelId = useId()

  const activeCount =
    view.filters.types.length +
    view.filters.statuses.length +
    view.filters.familyIds.length +
    (view.filters.needsMyVote ? 1 : 0)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="sugg-filter-menu" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`sugg-filter-menu__trigger${activeCount ? ' is-active' : ''}`}
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        Filters
        {activeCount ? <span className="sugg-filter-menu__count">{activeCount}</span> : null}
      </button>

      {open ? (
        <div className="sugg-filter-menu__panel" id={panelId} role="group" aria-label="Filters">
          <FilterGroup label="Type">
            {TYPES.map((type) => (
              <button
                key={type}
                type="button"
                className={`sugg-chip${view.filters.types.includes(type) ? ' is-on' : ''}`}
                aria-pressed={view.filters.types.includes(type)}
                onClick={() => suggestionStore.toggleType(type)}
              >
                {TYPE_LABEL[type]}
              </button>
            ))}
          </FilterGroup>

          <FilterGroup label="Status">
            {STATUSES.map((status) => (
              <button
                key={status}
                type="button"
                className={`sugg-chip${view.filters.statuses.includes(status) ? ' is-on' : ''}`}
                aria-pressed={view.filters.statuses.includes(status)}
                onClick={() => suggestionStore.toggleStatus(status)}
              >
                {STATUS_LABEL[status]}
              </button>
            ))}
          </FilterGroup>

          {families.length > 0 ? (
            <FilterGroup label="Family">
              {families.map((family) => (
                <button
                  key={family.id}
                  type="button"
                  className={`sugg-chip${view.filters.familyIds.includes(family.id) ? ' is-on' : ''}`}
                  aria-pressed={view.filters.familyIds.includes(family.id)}
                  onClick={() => suggestionStore.toggleFamily(family.id)}
                  style={{ '--sugg-chip-accent': familyColor(family) ?? undefined } as CSSProperties}
                >
                  <span className="sugg-chip__dot" aria-hidden="true" />
                  {family.name}
                </button>
              ))}
            </FilterGroup>
          ) : null}

          {hasActiveFilters(view.filters) ? (
            <button
              type="button"
              className="sugg-filters__clear"
              onClick={() => suggestionStore.clearFilters()}
            >
              Clear filters
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="sugg-filter-menu__group" role="group" aria-label={`Filter by ${label.toLowerCase()}`}>
      <div className="sugg-filter-menu__group-label">{label}</div>
      <div className="sugg-filters__group">{children}</div>
    </div>
  )
}
