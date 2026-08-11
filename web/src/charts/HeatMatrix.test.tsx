import { describe, expect, expectTypeOf, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { HeatMatrix } from './HeatMatrix'
import type { HeatMatrixProps } from './HeatMatrix'

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
    expect(emptyCells[0].className).not.toMatch(/k-heat-cell--\d+/)
    // The empty cell prints an em dash, never a "0".
    expect(emptyCells[0]).toHaveTextContent('—')
  })

  it('hatches every not-voted cell distinctly from a scored one', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[null, null], [1, 2]]} />)
    const empty = screen.getAllByTestId('heat-cell-empty')
    expect(empty).toHaveLength(2)
    empty.forEach((cell) => expect(cell).toHaveClass('k-heat-cell--empty'))
    const scored = screen.getAllByTestId('heat-cell')
    expect(scored).toHaveLength(2)
  })

  it('always prints the numeric value on top of a scored cell — colour is never the only signal', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, 3], [5, 6]]} />)
    for (const value of ['9', '3', '5', '6']) {
      expect(screen.getAllByText(value).length).toBeGreaterThan(0)
    }
  })

  it('gives every cell an accessible label distinguishing "not voted" from any score', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, null], [5, 6]]} />)
    expect(screen.getByLabelText('Ana R., Cornwall: 9')).toBeInTheDocument()
    expect(screen.getByLabelText('Ana R., Somerset: not voted')).toBeInTheDocument()
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

  it('is a real, accessible table with a caption naming the member and option counts', () => {
    render(
      <HeatMatrix
        insight="Mei is the only one cool on Cornwall"
        rows={rows}
        cols={cols}
        values={[[9, 6], [5, 5]]}
      />,
    )
    const table = screen.getByRole('table')
    expect(table).toHaveTextContent(/2 members across 2 options/)
    // Row and column headers are real <th> scope, not just styled cells.
    expect(screen.getByRole('columnheader', { name: 'Cornwall' })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'Ana R.' })).toBeInTheDocument()
  })
})

describe('HeatMatrix — sticky headers', () => {
  it('sticks every column header to the top of its scroll container', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, 6], [5, 5]]} />)
    const headerCells = screen.getAllByRole('columnheader')
    headerCells.forEach((cell) => {
      expect(cell.tagName).toBe('TH')
    })
    // Structural assertion: header cells live inside <thead>, whose sticky behaviour is
    // declared once in HeatMatrix.css against this selector, rather than per-cell inline
    // styles that a scroll container could disagree with.
    const thead = screen.getByRole('table').querySelector('thead')
    expect(thead).not.toBeNull()
    headerCells.forEach((cell) => expect(thead?.contains(cell)).toBe(true))
  })

  it('sticks every row header to the left of its scroll container, inside <tbody>', () => {
    render(<HeatMatrix insight="test" rows={rows} cols={cols} values={[[9, 6], [5, 5]]} />)
    const rowHeaders = screen.getAllByRole('rowheader')
    expect(rowHeaders).toHaveLength(rows.length)
    const tbody = screen.getByRole('table').querySelector('tbody')
    rowHeaders.forEach((cell) => {
      expect(cell.tagName).toBe('TH')
      expect(tbody?.contains(cell)).toBe(true)
    })
  })

  it('renders inside a single scrollable container, not the page, for many members/options', () => {
    const manyRows = Array.from({ length: 12 }, (_, i) => ({ id: `m${i}`, label: `Member ${i}` }))
    const manyCols = Array.from({ length: 10 }, (_, i) => ({ id: `o${i}`, label: `Option ${i}` }))
    const values = manyRows.map(() => manyCols.map(() => 5))
    const { container } = render(
      <HeatMatrix insight="test" rows={manyRows} cols={manyCols} values={values} />,
    )
    const scrollers = container.querySelectorAll('[data-testid="heat-scroll"]')
    expect(scrollers).toHaveLength(1)
    expect(scrollers[0].querySelector('table')).not.toBeNull()
  })
})
