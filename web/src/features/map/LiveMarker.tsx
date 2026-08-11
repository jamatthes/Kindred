/**
 * LiveMarker — a live-location / check-in pin.
 *
 * Reuses `IdentityBadge` rather than reinventing a person marker, per the setup note in
 * this feature's brief and `plan/features/families/design.md`: "the one component that
 * renders a person anywhere in the product — map markers, member lists, the presence
 * stack, comment authors, the profile page." The family ring, the neutral-fill-on-initials
 * rule, and the no-broken-image guarantee all come for free from the badge.
 */

import { IdentityBadge } from '../../design/IdentityBadge'
import type { LiveMarkerSpec } from './types'
import './LiveMarker.css'

export type LiveMarkerProps = {
  marker: LiveMarkerSpec
  onClick?: (id: string) => void
  onHoverChange?: (hovering: boolean) => void
}

export function LiveMarker({ marker, onClick, onHoverChange }: LiveMarkerProps) {
  return (
    <button
      type="button"
      className={['k-live-marker', marker.selected ? 'is-selected' : ''].filter(Boolean).join(' ')}
      onClick={() => onClick?.(marker.id)}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
      data-testid="live-marker"
    >
      <IdentityBadge
        initials={marker.initials}
        familyColor={marker.familyColor}
        size={40}
        name={marker.name}
        offline={marker.online === false}
      />
    </button>
  )
}
