/**
 * FamilyDistanceExpander — the side panel's distance block (D3, `design.md` > "Placement"):
 * own family's chip shown immediately, an expander revealing every family's row with its
 * colour accent. Deliberately open to every member — "fairness arguments need shared data."
 */

import { useState } from 'react'
import { familyColor } from '../../design/familyColor'
import { DistanceChip } from './DistanceChip'
import type { DistanceOut, SuggestionType } from '../../app/types'
import './distances.css'

export type FamilyDistanceExpanderProps = {
  distances: DistanceOut[]
  ownFamilyId: string | null
  suggestionType: SuggestionType
  canRetryFailed?: boolean
  onRetryFamily?: (familyId: string) => void
  onSetHomeFor?: (familyId: string) => void
}

export function FamilyDistanceExpander({
  distances,
  ownFamilyId,
  suggestionType,
  canRetryFailed = false,
  onRetryFamily,
  onSetHomeFor,
}: FamilyDistanceExpanderProps) {
  const [expanded, setExpanded] = useState(false)

  if (distances.length === 0) return null

  const own = distances.find((d) => d.family_id === ownFamilyId) ?? distances[0]
  const others = distances.filter((d) => d.family_id !== own.family_id)
  const isRegion = suggestionType === 'region'

  return (
    <div className="dist-expander">
      <DistanceChip
        distance={own}
        isRegion={isRegion}
        canRetry={canRetryFailed}
        onRetry={() => onRetryFamily?.(own.family_id)}
        onSetHome={() => onSetHomeFor?.(own.family_id)}
      />

      {others.length > 0 ? (
        <button
          type="button"
          className="dist-expander__toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? 'Hide other families' : `Show all ${distances.length} families`}
        </button>
      ) : null}

      {expanded ? (
        <ul className="dist-expander__list">
          {others.map((d) => (
            <li key={d.family_id} className="dist-expander__row">
              <span
                className="dist-expander__swatch"
                aria-hidden="true"
                style={{ background: familyColor({ color: d.family_color, color_custom: d.family_color_custom ?? null }) ?? 'var(--color-border-strong)' }}
              />
              <DistanceChip
                distance={d}
                isRegion={isRegion}
                canRetry={canRetryFailed}
                onRetry={() => onRetryFamily?.(d.family_id)}
                onSetHome={() => onSetHomeFor?.(d.family_id)}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
