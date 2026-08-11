import { describe, expect, expectTypeOf, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MiniBar, Sparkline } from './MiniBar'
import type { MiniBarProps, SparklineProps } from './MiniBar'

describe('MiniBar — honesty rules', () => {
  it('has no baseline prop; bars start at the strip floor', () => {
    expectTypeOf<MiniBarProps>().not.toHaveProperty('baseline')
    const { container } = render(<MiniBar insight="test" values={[9, 8, 9]} />)
    const bars = [...container.querySelectorAll('rect.k-chart__bar')]
    const bottoms = bars.map((bar) => Number(bar.getAttribute('y')) + Number(bar.getAttribute('height')))
    // Every bar's bottom edge sits on the same floor (the zero line), regardless of how
    // far the data is from zero.
    expect(new Set(bottoms).size).toBe(1)
  })

  it('renders an honest empty state with no data', () => {
    render(<MiniBar insight="No data yet" values={[]} />)
    expect(screen.getByText('No data yet.')).toBeInTheDocument()
  })
})

describe('Sparkline — honesty rules', () => {
  it('has no baseline/yMin/gridlines prop', () => {
    expectTypeOf<SparklineProps>().not.toHaveProperty('baseline')
    expectTypeOf<SparklineProps>().not.toHaveProperty('yMin')
    expectTypeOf<SparklineProps>().not.toHaveProperty('gridlines')
  })

  it('refuses to draw a trend line from a single point, falling back to a bar', () => {
    const { container } = render(<Sparkline insight="First point only" values={[6]} />)
    expect(container.querySelector('polyline')).toBeNull()
    expect(container.querySelector('rect.k-chart__bar')).not.toBeNull()
  })

  it('renders an honest empty state with no data', () => {
    render(<Sparkline insight="No data yet" values={[]} />)
    expect(screen.getByText('No data yet.')).toBeInTheDocument()
  })

  it('picks a wider aspect ratio for a more volatile series than a flat one', () => {
    const flat = render(<Sparkline insight="flat" values={[5, 5, 5, 5, 5]} />)
    const flatSvg = flat.container.querySelector('svg.k-chart__viz')!
    const flatWidth = Number(flatSvg.getAttribute('viewBox')!.split(' ')[2])
    flat.unmount()

    const volatile = render(<Sparkline insight="volatile" values={[0, 10, 0, 10, 0]} />)
    const volatileSvg = volatile.container.querySelector('svg.k-chart__viz')!
    const volatileWidth = Number(volatileSvg.getAttribute('viewBox')!.split(' ')[2])

    expect(volatileWidth).toBeGreaterThan(flatWidth)
  })
})
