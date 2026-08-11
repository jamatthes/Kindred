import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopoverCard } from './PopoverCard'

describe('PopoverCard', () => {
  it('renders title, category and status, compact and glanceable', () => {
    render(<PopoverCard title="Harbour House" category="accommodation" status="shortlisted" />)
    expect(screen.getByTestId('popover-card')).toHaveTextContent('Harbour House')
    expect(screen.getByText('Accommodation')).toBeInTheDocument()
    expect(screen.getByText('Shortlisted')).toBeInTheDocument()
  })

  it('renders the vote summary and distance chips slots when supplied', () => {
    render(
      <PopoverCard
        title="X"
        category="meal"
        status="proposed"
        voteSummary={<span data-testid="vote-slot">8.2</span>}
        distanceChips={<span data-testid="dist-slot">4h 05</span>}
      />,
    )
    expect(screen.getByTestId('vote-slot')).toBeInTheDocument()
    expect(screen.getByTestId('dist-slot')).toBeInTheDocument()
  })

  it('omits the vote/distance slots entirely when not supplied — no empty chrome', () => {
    render(<PopoverCard title="X" category="meal" status="proposed" />)
    expect(document.querySelector('.k-popover__votes')).toBeNull()
    expect(document.querySelector('.k-popover__distances')).toBeNull()
  })

  it('renders the comment count when supplied, singular/plural correctly', () => {
    const { rerender } = render(<PopoverCard title="X" category="meal" status="proposed" commentCount={1} />)
    expect(screen.getByText('1 comment')).toBeInTheDocument()
    rerender(<PopoverCard title="X" category="meal" status="proposed" commentCount={3} />)
    expect(screen.getByText('3 comments')).toBeInTheDocument()
  })

  it('the Details action is a callback, not a link/navigation', () => {
    const onDetails = vi.fn()
    render(<PopoverCard title="X" category="meal" status="proposed" onDetails={onDetails} />)
    const button = screen.getByRole('button', { name: 'Details' })
    expect(button.tagName.toLowerCase()).toBe('button')
    fireEvent.click(button)
    expect(onDetails).toHaveBeenCalledTimes(1)
  })

  it('omits the Details button when no handler is supplied', () => {
    render(<PopoverCard title="X" category="meal" status="proposed" />)
    expect(screen.queryByRole('button', { name: 'Details' })).toBeNull()
  })

  it('renders the "Open in Maps" action only when supplied', () => {
    const onOpenInMaps = vi.fn()
    const { rerender } = render(<PopoverCard title="X" category="meal" status="proposed" />)
    expect(screen.queryByRole('button', { name: /Open in Maps/ })).toBeNull()
    rerender(<PopoverCard title="X" category="meal" status="proposed" onOpenInMaps={onOpenInMaps} />)
    fireEvent.click(screen.getByRole('button', { name: /Open in Maps/ }))
    expect(onOpenInMaps).toHaveBeenCalledTimes(1)
  })
})
