import { describe, expect, expectTypeOf, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AvgBar } from './AvgBar'
import type { AvgBarProps } from './AvgBar'

describe('AvgBar — honesty rules', () => {
  it('has no baseline, yMin, gridlines, shadow, depth, or gradientFill prop', () => {
    expectTypeOf<AvgBarProps>().not.toHaveProperty('baseline')
    expectTypeOf<AvgBarProps>().not.toHaveProperty('yMin')
    expectTypeOf<AvgBarProps>().not.toHaveProperty('gridlines')
    expectTypeOf<AvgBarProps>().not.toHaveProperty('shadow')
    expectTypeOf<AvgBarProps>().not.toHaveProperty('depth')
    expectTypeOf<AvgBarProps>().not.toHaveProperty('gradientFill')
  })

  it('titles the chart with the insight prop, not a metric-name prop', () => {
    expectTypeOf<AvgBarProps>().toHaveProperty('insight')
    expectTypeOf<AvgBarProps['insight']>().toBeString()
  })

  it('draws every bar starting from x = 0 (the zero baseline), for a dataset far from zero', () => {
    // 7-9 never gets near zero; the bar geometry must still start at the axis position.
    const { container } = render(
      <AvgBar
        insight="Cornwall edges ahead"
        items={[
          { label: 'Cornwall', value: 9 },
          { label: 'Somerset', value: 7 },
        ]}
      />,
    )
    const bars = container.querySelectorAll('rect.k-chart__bar, rect.k-chart__bar--dim')
    const axes = container.querySelectorAll('line.k-chart__axis')
    expect(axes.length).toBe(bars.length)
    expect(bars.length).toBe(2)
    axes.forEach((axis) => expect(axis.getAttribute('x1')).toBe('0'))
    bars.forEach((bar) => {
      expect(bar.getAttribute('x')).toBe('0')
    })
  })

  it('scales bar width proportionally to value within scaleMax, never truncated', () => {
    const { container } = render(
      <AvgBar insight="test" items={[{ label: 'A', value: 5 }]} scaleMax={10} />,
    )
    const bar = container.querySelector('rect.k-chart__bar')!
    const axis = container.querySelector('line.k-chart__axis')!
    // Widths are a percentage of the track, so half of scaleMax is exactly half of it,
    // whatever the container width happens to be.
    expect(bar.getAttribute('width')).toBe('50%')
    expect(axis).toBeTruthy()
  })

  it('renders every label as HTML text, not SVG <text>, so it obeys the type scale', () => {
    const { container } = render(
      <AvgBar
        insight="test"
        items={[{ label: 'A destination with a very long name indeed', value: 5 }]}
      />,
    )
    expect(container.querySelectorAll('text')).toHaveLength(0)
    const label = container.querySelector('.k-chart__label')!
    expect(label.tagName.toLowerCase()).toBe('span')
    // Long labels ellipsize rather than clip, and the full string stays reachable.
    expect(label).toHaveAttribute('title', 'A destination with a very long name indeed')
  })

  it('prints the axis ticks as HTML under the track', () => {
    const { container } = render(
      <AvgBar insight="test" items={[{ label: 'A', value: 5 }]} scaleMax={10} />,
    )
    const ticks = [...container.querySelectorAll('.k-chart__tick')].map((t) => t.textContent)
    expect(ticks).toEqual(['0', '10'])
  })
})

describe('AvgBar — rendering', () => {
  it('prints the value at the end of each bar and exposes an accessible summary', () => {
    render(
      <AvgBar
        insight="Cornwall leads by two full points"
        items={[
          { label: 'Cornwall', value: 8, count: 11 },
          { label: 'Somerset', value: 6, count: 10 },
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: /Cornwall leads by two full points/ })).toBeInTheDocument()
    expect(screen.getAllByText('8.0').length).toBeGreaterThan(0)
    expect(screen.getAllByText('6.0').length).toBeGreaterThan(0)
    // Accessible table fallback.
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Votes' })).toBeInTheDocument()
  })

  it('renders an honest empty state instead of an empty axis frame when there is no data', () => {
    render(<AvgBar insight="No scores yet" items={[]} />)
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('emphasises exactly one row with the accent colour', () => {
    const { container } = render(
      <AvgBar
        insight="test"
        items={[
          { label: 'A', value: 4 },
          { label: 'B', value: 9 },
          { label: 'C', value: 2 },
        ]}
      />,
    )
    const accented = container.querySelectorAll('rect.k-chart__bar:not(.k-chart__bar--dim)')
    expect(accented).toHaveLength(1)
  })
})
