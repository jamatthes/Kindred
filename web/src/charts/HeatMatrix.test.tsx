import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { HeatMatrix } from './HeatMatrix'
import type { HeatMatrixProps } from './HeatMatrix'
import { expectTypeOf } from 'vitest'

const rows = [
  { id: 'm1', label: 'Ana R.' },
  { id: 'm2', label: 'Mei J.' },
]
const cols = [
  { id: 'o1', label: 'Cornwall' },
  { id: 'o2', label: 'Somerset' },
]

describe('HeatMatrix — honesty rules', () => {
  it('never renders a null (not-voted) cell as a scored/coloured cell', () => {
    const { container } = render(
      <HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, null], [5, 6]]} />,
    )
    const emptyCells = container.querySelectorAll('[data-testid="heat-cell-empty"]')
    expect(emptyCells).toHaveLength(1)
    // The empty cell prints an em dash, never a "0".
    const dash = screen.getAllByText('—')
    expect(dash.length).toBeGreaterThan(0)
    const muted = container.querySelectorAll('.k-chart__cell-value--muted')
    expect(muted).toHaveLength(1)
    expect(muted[0]).toHaveTextContent('—')
  })

  it('hatches every not-voted cell with the shared pattern fill', () => {
    const { container } = render(
      <HeatMatrix insight="test" rows={rows} cols={cols} values={[[null, null], [1, 2]]} />,
    )
    const hatched = container.querySelectorAll('rect[fill^="url(#"]')
    expect(hatched).toHaveLength(2)
  })

  it('always prints the numeric value on top of a scored cell — colour is never the only signal', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, 3], [5, 6]]} />)
    // Values appear as visible text, not merely as a fill colour.
    for (const value of ['9', '3', '5', '6']) {
      expect(screen.getAllByText(value).length).toBeGreaterThan(0)
    }
  })

  it('provides a visually-hidden table fallback distinguishing "not voted" from any score', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, null], [5, 6]]} />)
    const table = screen.getByRole('table')
    expect(table).toHaveTextContent('not voted')
  })

  it('has no baseline/gridlines/shadow/depth/gradientFill prop', () => {
    expectTypeOf<HeatMatrixProps>().not.toHaveProperty('baseline')
    expectTypeOf<HeatMatrixProps>().not.toHaveProperty('gridlines')
    expectTypeOf<HeatMatrixProps>().not.toHaveProperty('shadow')
  })
})

describe('HeatMatrix — rendering', () => {
  it('renders an honest empty state with no rows or columns', () => {
    render(<HeatMatrix insight="No scores yet" rows={[]} cols={[]} values={[]} />)
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
  })

  it('exposes an accessible summary naming the member and option counts', () => {
    render(<HeatMatrix insight="Mei is the only one cool on Cornwall" rows={rows} cols={cols} values={[[9, 6], [5, 5]]} />)
    expect(
      screen.getByRole('img', { name: /Mei is the only one cool on Cornwall.*2 members.*2 options/ }),
    ).toBeInTheDocument()
  })
})
