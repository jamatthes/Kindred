import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { StyleguidePrimitives } from './StyleguidePrimitives'

describe('StyleguidePrimitives', () => {
  it('renders all three button variants in default, loading and disabled states', () => {
    render(<StyleguidePrimitives />)
    ;['Default', 'Loading', 'Disabled'].forEach((label) => {
      expect(screen.getAllByRole('button', { name: label }).length).toBe(3)
    })
  })

  it('renders the field gallery with a real focused field and a real error field', () => {
    render(<StyleguidePrimitives />)
    const fields = screen.getAllByLabelText('Trip name')
    expect(fields.length).toBeGreaterThanOrEqual(5)
    expect(document.activeElement).toBe(fields.find((f) => f === document.activeElement))
    expect(screen.getByText('A trip needs a name.')).toBeInTheDocument()
  })

  it('lets a toast be triggered from the gallery without a page-level ToastProvider', () => {
    render(<StyleguidePrimitives />)
    fireEvent.click(screen.getByRole('button', { name: 'Trigger a toast' }))
    expect(screen.getByText('Suggestion added to the board.')).toBeInTheDocument()
  })

  it('opens the bottom sheet demo as a real dialog', () => {
    render(<StyleguidePrimitives />)
    fireEvent.click(screen.getByRole('button', { name: 'Open bottom sheet' }))
    expect(screen.getByRole('dialog', { name: 'Trip details' })).toBeInTheDocument()
  })

  it('renders identity badges with their family-colour ring and initials fallback', () => {
    render(<StyleguidePrimitives />)
    expect(screen.getAllByTestId('badge').length).toBeGreaterThanOrEqual(4)
    expect(screen.getByText('AR')).toBeInTheDocument()
  })

  it('is honest that EmptyState is not yet a general-purpose primitive', () => {
    render(<StyleguidePrimitives />)
    expect(screen.getByText(/no general-purpose `EmptyState` primitive/)).toBeInTheDocument()
  })
})
