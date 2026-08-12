/**
 * DistancePerspectiveSelector — "sort by distance from the Hendersons" (D4). Switches
 * `map-suggestions/store.ts`'s shared `distancePerspectiveFamilyId`; the list/map column
 * header names whichever family is active so a sorted list is never ambiguous about whose
 * driving time it shows (`design.md` > "Sorting").
 */

import { useFamilies } from '../families/useFamilies'
import { suggestionStore, useSuggestionView } from '../map-suggestions/store'
import './distances.css'

export function DistancePerspectiveSelector({ ownFamilyId }: { ownFamilyId: string | null }) {
  const { families } = useFamilies()
  const view = useSuggestionView()

  if (families.length <= 1) return null

  return (
    <label className="dist-perspective">
      <span>Distance from</span>
      <select
        value={view.distancePerspectiveFamilyId ?? ownFamilyId ?? ''}
        onChange={(e) => {
          const value = e.target.value
          suggestionStore.setDistancePerspective(value === ownFamilyId ? null : value)
        }}
      >
        {families.map((family) => (
          <option key={family.id} value={family.id}>
            {family.id === ownFamilyId ? `${family.name} (you)` : family.name}
          </option>
        ))}
      </select>
    </label>
  )
}
