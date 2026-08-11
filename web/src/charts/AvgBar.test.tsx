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
    const axis = container.querySelector('line.k-chart__axis')
    expect(axis).not.toBeNull()
    const axisX = axis!.getAttribute('x1')
    bars.forEach((bar) => {
      expect(bar.getAttribute('x')).toBe(axisX)
    })
  })

  it('scales bar width proportionally to value within scaleMax, never truncated', () => {
    const { container } = render(
      <AvgBar insight="test" items={[{ label: 'A', value: 5 }]} scaleMax={10} />,
    )
    const bar = container.querySelector('rect.k-chart__bar')!
    const axis = container.querySelector('line.k-chart__axis')!
    const trackWidth = 340 - 104 - 8 // CHART_W - LABEL_W - PAD, mirrors the component constants
    // Half of scaleMax (10) should be roughly half the track.
    expect(Number(bar.getAttribute('width'))).toBeCloseTo(trackWidth / 2, 0)
    expect(axis).toBeTruthy()
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
