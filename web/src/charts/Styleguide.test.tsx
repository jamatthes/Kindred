import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Styleguide } from './Styleguide'

describe('Styleguide', () => {
  it('renders every widget with its accessible role', () => {
    render(<Styleguide />)
    const charts = screen.getAllByRole('img')
    // 6 widgets with realistic data + 5 empty-state variants.
    expect(charts.length).toBeGreaterThanOrEqual(11)
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
