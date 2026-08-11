import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SuggestionPin, suggestionPinClassName } from './SuggestionPin'
import type { SuggestionMarkerSpec } from './types'

const base: SuggestionMarkerSpec = {
  id: 's1',
  kind: 'suggestion',
  position: { lat: 50.4, lng: -4.7 },
  category: 'accommodation',
  status: 'proposed',
  familyColor: 3,
}

describe('SuggestionPin', () => {
  it('renders a per-category icon and exposes the category/status as data attributes', () => {
    render(<SuggestionPin marker={base} label="Harbour House" />)
    const pin = screen.getByTestId('suggestion-pin')
    expect(pin).toHaveAttribute('data-category', 'accommodation')
    expect(pin).toHaveAttribute('data-status', 'proposed')
  })

  it('never carries status by colour alone: every non-proposed status renders a distinct glyph', () => {
    const statuses: SuggestionMarkerSpec['status'][] = ['shortlisted', 'approved', 'rejected', 'scheduled']
    const glyphs = new Set<string>()
    for (const status of statuses) {
      const { unmount, container } = render(<SuggestionPin marker={{ ...base, status }} label="X" />)
      const glyph = container.querySelector('.k-pin__status-glyph')
      expect(glyph).not.toBeNull()
      glyphs.add(glyph!.textContent ?? '')
      unmount()
    }
    // Every status's glyph is unique — nothing collapses two statuses to the same mark.
    expect(glyphs.size).toBe(statuses.length)
  })

  it('proposed (the baseline status) renders no glyph badge', () => {
    render(<SuggestionPin marker={{ ...base, status: 'proposed' }} label="X" />)
    expect(document.querySelector('.k-pin__status-glyph')).toBeNull()
  })

  it('rejected is visually muted in addition to carrying its glyph', () => {
    render(<SuggestionPin marker={{ ...base, status: 'rejected' }} label="X" />)
    expect(screen.getByTestId('suggestion-pin')).toHaveClass('k-pin--rejected')
  })

  it('falls back to a neutral ring colour when the suggestion has no family yet', () => {
    render(<SuggestionPin marker={{ ...base, familyColor: null }} label="X" />)
    expect(screen.getByTestId('suggestion-pin')).toHaveStyle({ background: 'var(--color-text-muted)' })
  })

  it('uses the family colour token when one is set', () => {
    render(<SuggestionPin marker={base} label="X" />)
    expect(screen.getByTestId('suggestion-pin')).toHaveStyle({ background: 'var(--family-3)' })
  })

  it('calls onClick with the marker id', () => {
    const onClick = vi.fn()
    render(<SuggestionPin marker={base} label="X" onClick={onClick} />)
    fireEvent.click(screen.getByTestId('suggestion-pin'))
    expect(onClick).toHaveBeenCalledWith('s1')
  })

  it('reports hover changes', () => {
    const onHoverChange = vi.fn()
    render(<SuggestionPin marker={base} label="X" onHoverChange={onHoverChange} />)
    const pin = screen.getByTestId('suggestion-pin')
    fireEvent.mouseEnter(pin)
    fireEvent.mouseLeave(pin)
    expect(onHoverChange).toHaveBeenNthCalledWith(1, true)
    expect(onHoverChange).toHaveBeenNthCalledWith(2, false)
  })

  it('is keyboard reachable and has an accessible name including category and status', () => {
    render(<SuggestionPin marker={base} label="Harbour House" />)
    expect(screen.getByRole('button', { name: /Harbour House — accommodation, proposed/ })).toBeInTheDocument()
  })
})

describe('suggestionPinClassName', () => {
  it('adds is-selected only when selected', () => {
    expect(suggestionPinClassName({ status: 'proposed', selected: true })).toContain('is-selected')
    expect(suggestionPinClassName({ status: 'proposed', selected: false })).not.toContain('is-selected')
  })
})
