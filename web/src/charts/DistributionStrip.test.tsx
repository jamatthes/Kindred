import { describe, expect, expectTypeOf, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DistributionStrip } from './DistributionStrip'
import type { DistributionStripProps } from './DistributionStrip'

describe('DistributionStrip — honesty rules', () => {
  it('has no gridlines/shadow/depth/gradientFill prop', () => {
    expectTypeOf<DistributionStripProps>().not.toHaveProperty('gridlines')
    expectTypeOf<DistributionStripProps>().not.toHaveProperty('shadow')
    expectTypeOf<DistributionStripProps>().not.toHaveProperty('gradientFill')
  })

  it('pairs every segment with an icon and a count label — colour is never the only signal', () => {
    render(<DistributionStrip insight="test" up={7} down={2} none={2} />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    items.forEach((item) => {
      expect(item.querySelector('svg')).not.toBeNull()
    })
    expect(screen.getAllByText('7').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
  })

  it('segment widths are proportional to their share of the total', () => {
    const { container } = render(<DistributionStrip insight="test" up={5} down={5} none={0} />)
    const up = container.querySelector('.k-chart__seg--up')!
    const down = container.querySelector('.k-chart__seg--down')!
    expect(Number(up.getAttribute('width'))).toBeCloseTo(Number(down.getAttribute('width')), 1)
  })
})

describe('DistributionStrip — rendering', () => {
  it('renders an honest empty state when nobody has voted', () => {
    render(<DistributionStrip insight="No votes yet" up={0} down={0} none={0} />)
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
  })

  it('omits a zero-count segment from the strip but keeps it in the legend', () => {
    const { container } = render(<DistributionStrip insight="test" up={10} down={0} none={0} />)
    expect(container.querySelector('.k-chart__seg--down')).toBeNull()
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })
})
