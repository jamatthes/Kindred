import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChartEmptyState, VisuallyHidden } from './a11y'

describe('VisuallyHidden', () => {
  it('keeps content in the accessibility tree while hiding it visually', () => {
    render(<VisuallyHidden>Score matrix, 3 members by 2 options</VisuallyHidden>)
    const node = screen.getByText('Score matrix, 3 members by 2 options')
    expect(node).toBeInTheDocument()
    expect(node).toHaveClass('k-chart-visually-hidden')
  })
})

describe('ChartEmptyState', () => {
  it('renders inside a labelled role="img" so an empty chart is never silent to a screen reader', () => {
    render(<ChartEmptyState insight="No scores yet" message="No votes yet." />)
    expect(screen.getByRole('img', { name: 'No scores yet — No votes yet.' })).toBeInTheDocument()
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
  })
})
