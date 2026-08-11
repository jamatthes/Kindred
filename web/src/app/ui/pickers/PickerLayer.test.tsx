/**
 * The two surfaces a picker can open into. jsdom reports no matches for any media query by
 * default (see `src/test/setup.ts`), so the sheet branch is exercised by answering the one
 * query the layer asks about.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PickerLayer } from './PickerLayer'
import { PICKER_SHEET_QUERY } from '../../../design/breakpoints'

const realMatchMedia = window.matchMedia

function answerSheetQuery(matches: boolean) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: query === PICKER_SHEET_QUERY ? matches : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

afterEach(() => {
  window.matchMedia = realMatchMedia
})

describe('PickerLayer', () => {
  it('renders nothing while closed', () => {
    render(
      <PickerLayer open={false} title="Start date" onClose={() => {}}>
        <p>calendar</p>
      </PickerLayer>,
    )
    expect(screen.queryByText('calendar')).not.toBeInTheDocument()
  })

  it('is a labelled popover dialog on a wide viewport', () => {
    answerSheetQuery(false)
    render(
      <PickerLayer open title="Start date" onClose={() => {}}>
        <p>calendar</p>
      </PickerLayer>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Start date' })
    expect(dialog).toHaveClass('k-picker-popover')
  })

  it('dismisses the popover on a click outside it', () => {
    answerSheetQuery(false)
    let closed = 0
    render(
      <PickerLayer open title="Start date" onClose={() => (closed += 1)}>
        <p>calendar</p>
      </PickerLayer>,
    )
    fireEvent.pointerDown(document.body)
    expect(closed).toBe(1)
    fireEvent.pointerDown(screen.getByText('calendar'))
    expect(closed).toBe(1)
  })

  it('opens in the bottom sheet, at its full snap, below the picker breakpoint', () => {
    answerSheetQuery(true)
    render(
      <PickerLayer open title="Start date" onClose={() => {}}>
        <p>calendar</p>
      </PickerLayer>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Start date' })
    expect(dialog).toHaveClass('sheet', 'sheet--full')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    // The sheet's own dismissal affordances, not a second set invented here.
    expect(screen.getByRole('button', { name: 'Collapse' })).toBeInTheDocument()
  })
})
