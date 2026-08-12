/**
 * DistanceCell — the list row's distance value (`design.md` > "Placement": "own family's
 * value in the distance column, right-aligned with tabular figures per the data-table
 * pattern"). Plain text rather than the full `DistanceChip` — a table cell has no room for
 * an icon and a tooltip, and the column header already supplies the context (whose
 * perspective, and that the unit is driving time) a bare cell can't carry on its own.
 */

import { formatDistanceMeters, formatDuration } from './format'
import type { DistanceOut } from '../../app/types'

export function DistanceCell({ distance }: { distance: DistanceOut | null }) {
  if (!distance) return <span className="tabular">—</span>

  switch (distance.status) {
    case 'ok':
      return distance.duration_s !== null ? (
        <span className="tabular">{formatDuration(distance.duration_s)}</span>
      ) : (
        <span className="tabular">—</span>
      )
    case 'pending':
      return (
        <span className="tabular dist-cell--estimate">
          {distance.distance_m !== null ? `~${formatDistanceMeters(distance.distance_m)}` : '—'}
        </span>
      )
    case 'no_route':
      return <span className="tabular dist-cell--muted">No route</span>
    case 'failed':
      return <span className="tabular dist-cell--muted">Unavailable</span>
    case 'no_home':
      return <span className="tabular dist-cell--muted">No home set</span>
  }
}
