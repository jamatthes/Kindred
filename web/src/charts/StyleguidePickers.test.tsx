import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { StyleguidePickers } from './StyleguidePickers'

describe('StyleguidePickers', () => {
  it('shows every picker in both themes, in its own themed panel', () => {
    render(<StyleguidePickers />)
    const panels = document.querySelectorAll('[data-theme]')
    const themes = [...panels].map((panel) => panel.getAttribute('theme') ?? panel.getAttribute('data-theme'))
    expect(themes).toContain('light')
    expect(themes).toContain('dark')
    // Two panels per section, two sections.
    expect(panels).toHaveLength(4)
  })

  it('renders the range, single and time pickers as live components', () => {
    render(<StyleguidePickers />)
    expect(screen.getAllByLabelText('Start date', { selector: 'input' }).length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText('Day of the trip', { selector: 'input' }).length).toBe(2)
    expect(screen.getAllByLabelText('Start time', { selector: 'input' }).length).toBeGreaterThan(0)
  })

  it('documents the error and disabled states rather than only the happy one', () => {
    render(<StyleguidePickers />)
    expect(
      screen.getAllByText('The end date cannot be before the start date.').length,
    ).toBe(2)
    const disabledInputs = [...document.querySelectorAll('input')].filter((i) => i.disabled)
    expect(disabledInputs.length).toBeGreaterThan(0)
  })

  it('stages the mid-hover range, which no still page could otherwise show', () => {
    render(<StyleguidePickers />)
    const grids = screen.getAllByRole('grid')
    expect(grids).toHaveLength(2) // one staged month per theme
    const painted = [...within(grids[0]).getAllByRole('button')].filter((cell) =>
      cell.className.includes('preview'),
    )
    expect(painted.length).toBe(6) // the 18th to the 23rd, between the locked start and the cursor
  })

  it('states the keyboard map on the page, not only in the code', () => {
    render(<StyleguidePickers />)
    expect(screen.getByText(/Shift\+PageUp\/PageDown a year/)).toBeInTheDocument()
  })
})
