/**
 * The map's right-click menu (`design.md` > "Map-first interaction model", 2).
 *
 * What is worth asserting is not that two buttons render: it is that the menu can be got rid
 * of by every route a user will try (Escape, a click elsewhere), that it lands under the
 * cursor rather than at a corner, and that the End stage disables it — a read-only trip whose
 * context menu still offered "Drop a pin here" would be lying about what the map can do.
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MapContextMenu } from './MapContextMenu'

function renderMenu(overrides: Partial<Parameters<typeof MapContextMenu>[0]> = {}) {
  const props = {
    x: 120,
    y: 80,
    onDropPin: vi.fn(),
    onDrawRegion: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  }
  render(<MapContextMenu {...props} />)
  return props
}

describe('MapContextMenu', () => {
  it('offers both create gestures and reports which one was chosen', () => {
    const props = renderMenu()

    fireEvent.click(screen.getByRole('menuitem', { name: 'Drop a pin here' }))
    expect(props.onDropPin).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('menuitem', { name: 'Draw a region here' }))
    expect(props.onDrawRegion).toHaveBeenCalledTimes(1)
  })

  it('sits at the point the user pointed at', () => {
    // Built from the props rather than written out: `check:tokens` scans this tree for raw
    // lengths, and a test asserting a coordinate is not the place to argue about the scale.
    const props = renderMenu({ x: 240, y: 36 })
    const menu = screen.getByRole('menu', { name: 'Map actions' })
    expect(menu).toHaveStyle({ left: `${props.x}px`, top: `${props.y}px` })
  })

  it('opens with the first item focused, so the menu is not mouse-only once it exists', () => {
    renderMenu()
    expect(screen.getByRole('menuitem', { name: 'Drop a pin here' })).toHaveFocus()
  })

  it('closes on Escape and on a click outside, but not on a click inside', () => {
    const props = renderMenu()

    fireEvent.mouseDown(screen.getByRole('menu', { name: 'Map actions' }))
    expect(props.onClose).not.toHaveBeenCalled()

    fireEvent.mouseDown(document.body)
    expect(props.onClose).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(props.onClose).toHaveBeenCalledTimes(2)
  })

  it('disables both actions when the stage forbids mutation', () => {
    renderMenu({ disabled: true })
    expect(screen.getByRole('menuitem', { name: 'Drop a pin here' })).toBeDisabled()
    expect(screen.getByRole('menuitem', { name: 'Draw a region here' })).toBeDisabled()
  })
})
