import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { LiveMarker } from './LiveMarker'
import type { LiveMarkerSpec } from './types'

const base: LiveMarkerSpec = {
  id: 'u1',
  kind: 'live',
  position: { lat: 50.4, lng: -4.7 },
  familyColor: 'var(--family-5)',
  initials: 'JB',
  name: 'Jibby',
  online: true,
}

describe('LiveMarker', () => {
  it('reuses the identity badge rather than reinventing a person marker', () => {
    render(<LiveMarker marker={base} />)
    expect(screen.getByTestId('badge')).toBeInTheDocument()
    expect(screen.getByTestId('badge')).toHaveTextContent('JB')
  })

  it('renders at the identity badge map-marker size', () => {
    render(<LiveMarker marker={base} />)
    expect(screen.getByTestId('badge')).toHaveClass('k-badge--40')
  })

  it('is offline-dimmed when the family has nobody online, via the badge itself', () => {
    render(<LiveMarker marker={{ ...base, online: false }} />)
    expect(screen.getByTestId('badge')).toHaveClass('is-offline')
  })

  it('always carries the name — colour/ring is never the only identifier', () => {
    render(<LiveMarker marker={base} />)
    expect(screen.getByTestId('badge')).toHaveAttribute('title', 'Jibby')
  })

  it('calls onClick with the marker id', () => {
    const onClick = vi.fn()
    render(<LiveMarker marker={base} onClick={onClick} />)
    fireEvent.click(screen.getByTestId('live-marker'))
    expect(onClick).toHaveBeenCalledWith('u1')
  })
})
