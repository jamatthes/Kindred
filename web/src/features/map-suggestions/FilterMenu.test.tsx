/**
 * The filters dropdown that replaced the permanent chip band (`design.md` > "List/table
 * specifics", revised 2026-08-12). Two things have to stay true for that trade to be worth
 * it: the chips must be reachable, and the closed trigger must still say when something is
 * filtered — otherwise a hidden filter silently explains away a missing suggestion.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { FilterMenu } from './FilterMenu'
import { suggestionStore } from './store'

vi.mock('../families/useFamilies', () => ({
  useFamilies: () => ({ families: [{ id: 'f1', name: 'Matthes', color: 2 }], loading: false, error: null }),
}))

describe('FilterMenu', () => {
  beforeEach(() => {
    suggestionStore.reset()
  })

  it('keeps the chips out of the layout until asked for', () => {
    render(<FilterMenu />)
    expect(screen.queryByRole('button', { name: 'Accommodation' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Filters/ }))
    expect(screen.getByRole('button', { name: 'Accommodation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shortlisted' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Matthes/ })).toBeInTheDocument()
  })

  it('toggling a chip writes the shared store', () => {
    render(<FilterMenu />)
    fireEvent.click(screen.getByRole('button', { name: /Filters/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Meal' }))
    expect(suggestionStore.getState().filters.types).toEqual(['meal'])
  })

  it('the closed trigger reports how many filters are on', () => {
    render(<FilterMenu />)
    const trigger = screen.getByRole('button', { name: /Filters/ })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: 'Meal' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approved' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('button', { name: 'Meal' })).not.toBeInTheDocument()
    expect(trigger).toHaveTextContent('2')
  })

  it('closes on an outside click', () => {
    render(<FilterMenu />)
    fireEvent.click(screen.getByRole('button', { name: /Filters/ }))
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('button', { name: 'Accommodation' })).not.toBeInTheDocument()
  })
})
