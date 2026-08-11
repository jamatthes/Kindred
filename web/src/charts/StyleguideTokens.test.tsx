import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StyleguideTokens } from './StyleguideTokens'

describe('StyleguideTokens', () => {
  it('renders a light and a dark panel, each with its own data-theme', () => {
    const { container } = render(<StyleguideTokens />)
    const panels = container.querySelectorAll('.k-sg-panel')
    expect(panels).toHaveLength(2)
    const themes = [...panels].map((panel) => panel.getAttribute('data-theme'))
    expect(themes.sort()).toEqual(['dark', 'light'])
  })

  it('shows the full 0-10 preference ramp as swatches in both panels', () => {
    render(<StyleguideTokens />)
    // "0" through "10" appear once per theme panel, twice total for the swatch labels
    // (plus once more per panel in the tint row).
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('10').length).toBeGreaterThanOrEqual(2)
  })

  it('renders a contrast readout row with a pass/fail badge for every status pairing', () => {
    render(<StyleguideTokens />)
    const badges = screen.getAllByTestId('aa-badge')
    // 7 pairings x 2 themes.
    expect(badges).toHaveLength(14)
    badges.forEach((badge) => {
      expect(badge.textContent).toMatch(/Pass|Fail/)
    })
  })

  it('renders the theme-invariant type and spacing scales once, not per theme', () => {
    const { container } = render(<StyleguideTokens />)
    expect(container.querySelectorAll('.k-sg-type-row')).toHaveLength(6)
    expect(container.querySelectorAll('.k-sg-space-row')).toHaveLength(6)
  })
})
