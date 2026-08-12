import { describe, expect, expectTypeOf, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SpreadDots } from './SpreadDots'
import type { SpreadDotsProps } from './SpreadDots'

describe('SpreadDots — honesty rules', () => {
  it('has no baseline/yMin prop and always uses the full 0-10 axis', () => {
    expectTypeOf<SpreadDotsProps>().not.toHaveProperty('baseline')
    expectTypeOf<SpreadDotsProps>().not.toHaveProperty('yMin')
  })

  it('renders the same axis length whether scores are tightly clustered or not', () => {
    const span = (container: HTMLElement) => {
      const axis = container.querySelector('line.k-chart__axis')!
      return [axis.getAttribute('x1'), axis.getAttribute('x2')]
    }

    const tight = render(
      <SpreadDots insight="tight" options={[{ label: 'Cornwall', scores: [8, 9, 8, 9] }]} />,
    )
    const tightSpan = span(tight.container)
    tight.unmount()

    const wide = render(
      <SpreadDots insight="wide" options={[{ label: 'Lakes', scores: [1, 5, 9] }]} />,
    )

    // The axis represents the fixed 0-10 range, not the data's own min/max, so a tight
    // cluster gets the same track as a wide spread — now the full track, both times.
    expect(tightSpan).toEqual(['0', '100%'])
    expect(span(wide.container)).toEqual(tightSpan)
  })

  it('positions dots as a percentage of the fixed 0-10 axis', () => {
    const { container } = render(
      <SpreadDots insight="test" options={[{ label: 'Cornwall', scores: [0, 5, 10] }]} />,
    )
    const cxs = [...container.querySelectorAll('circle.k-chart__dot')].map((d) =>
      d.getAttribute('cx'),
    )
    expect(cxs).toEqual(['0%', '50%', '100%'])
  })

  it('fans out colliding dots rather than hiding the collision', () => {
    const { container } = render(
      <SpreadDots insight="test" options={[{ label: 'Cornwall', scores: [8, 8, 8] }]} />,
    )
    const dots = container.querySelectorAll('circle.k-chart__dot')
    expect(dots).toHaveLength(3)
    const cys = new Set([...dots].map((dot) => dot.getAttribute('cy')))
    expect(cys.size).toBe(3)
  })

  it('marks the mean with a distinct tick', () => {
    const { container } = render(
      <SpreadDots insight="test" options={[{ label: 'Cornwall', scores: [8, 10] }]} />,
    )
    expect(container.querySelector('line.k-chart__mean-tick')).not.toBeNull()
  })
})

describe('SpreadDots — rendering', () => {
  it('renders an honest empty state with no options', () => {
    render(<SpreadDots insight="No scores yet" options={[]} />)
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
  })

  it('exposes an accessible table fallback with per-option means', () => {
    render(<SpreadDots insight="test" options={[{ label: 'Cornwall', scores: [8, 10] }]} />)
    const table = screen.getByRole('table')
    expect(table).toHaveTextContent('9.0')
  })

  it('draws no SVG text — every label and number is HTML at token size', () => {
    const { container } = render(
      <SpreadDots
        insight="test"
        options={[{ label: 'Cornwall · spread 0.7 · split', scores: [8, 10] }]}
      />,
    )
    expect(container.querySelectorAll('text')).toHaveLength(0)
    // The label that used to be clipped to "wall · spread 0.7" is present in full.
    const label = container.querySelector('.k-chart__label')!
    expect(label).toHaveTextContent('Cornwall · spread 0.7 · split')
    expect(label).toHaveAttribute('title', 'Cornwall · spread 0.7 · split')
  })
})
