import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Styleguide } from './Styleguide'

describe('Styleguide', () => {
  it('renders every SVG widget with its accessible role', () => {
    render(<Styleguide />)
    const charts = screen.getAllByRole('img')
    // 6 widgets with realistic data (HeatMatrix's real <table> isn't one of them — see
    // HeatMatrix.tsx) + 5 empty-state variants (HeatMatrix's *empty* state still renders
    // the shared ChartEmptyState, which is role="img").
    expect(charts.length).toBeGreaterThanOrEqual(10)
  })

  it('renders HeatMatrix as a real, accessible table', () => {
    render(<Styleguide />)
    expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(1)
  })

  it('has a page-scoped theme toggle that does not touch the document root', () => {
    render(<Styleguide />)
    const group = screen.getByRole('group', { name: 'Theme' })
    expect(group).toBeInTheDocument()
    const darkButton = screen.getByRole('button', { name: 'Dark' })
    fireEvent.click(darkButton)
    expect(darkButton).toHaveAttribute('aria-pressed', 'true')
    // The document root theme is untouched — this is scoped to the page's own wrapper.
    expect(document.documentElement.dataset.theme).not.toBe('dark')
  })
})
