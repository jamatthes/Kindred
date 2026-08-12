/**
 * The badge, and specifically the promise that it has no broken state.
 *
 * `plan/features/families/design.md`: "A missing or broken image URL renders the initials
 * rather than a broken-image glyph." That is the sort of guarantee that is true when written
 * and quietly false a year later, so it is asserted rather than described.
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { IdentityBadge } from './IdentityBadge'

describe('IdentityBadge', () => {
  it('renders the initials it is given, and does not compute them', () => {
    // The server computes `initials` so every surface agrees. A badge that derived them
    // would be a second implementation, and the two would diverge on the first mononym.
    render(<IdentityBadge initials="AL" name="Ada Lovelace" />)
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('renders one letter for a mononym without complaining', () => {
    render(<IdentityBadge initials="M" name="Mum" />)
    expect(screen.getByText('M')).toBeInTheDocument()
  })

  it('shows the avatar when there is one', () => {
    render(
      <IdentityBadge
        initials="AL"
        name="Ada Lovelace"
        avatarThumbUrl="/api/v1/attachments/1/abc-64.webp"
      />,
    )
    expect(screen.getByRole('img', { name: 'Ada Lovelace' })).toBeInTheDocument()
  })

  it('falls back to initials when the image fails, with no broken-image glyph', () => {
    render(
      <IdentityBadge initials="AL" name="Ada Lovelace" avatarThumbUrl="/gone.webp" />,
    )
    fireEvent.error(screen.getByRole('img', { name: 'Ada Lovelace' }))

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('keeps the initials in the DOM underneath the image', () => {
    // Which is *why* there is no broken state: the fallback is not swapped in on failure,
    // it was there all along and the image was covering it.
    render(<IdentityBadge initials="AL" name="Ada" avatarThumbUrl="/a.webp" />)
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('carries the family colour as a ring, never as the fill', () => {
    // Initials sit on a neutral fill so contrast does not depend on which of the eight slots
    // a family holds. The ring is the family carrier.
    render(<IdentityBadge initials="AL" familyColor="var(--family-5)" name="Ada" />)
    const badge = screen.getByTestId('badge')
    expect(badge.style.borderColor).toBe('var(--family-5)')
    expect(badge.style.background).toBe('')
  })

  it('always carries a name, so colour is never the only identifier', () => {
    render(<IdentityBadge initials="AL" familyColor="var(--family-3)" name="Ada Lovelace" />)
    expect(screen.getByTestId('badge')).toHaveAttribute('title', 'Ada Lovelace')
  })

  it('requests the small rendition below 64 and the large one at 64', () => {
    const { rerender } = render(
      <IdentityBadge
        initials="AL"
        name="Ada"
        size={32}
        avatarUrl="/full.webp"
        avatarThumbUrl="/thumb.webp"
      />,
    )
    expect(screen.getByRole('img')).toHaveAttribute('src', '/thumb.webp')

    rerender(
      <IdentityBadge
        initials="AL"
        name="Ada"
        size={64}
        avatarUrl="/full.webp"
        avatarThumbUrl="/thumb.webp"
      />,
    )
    expect(screen.getByRole('img')).toHaveAttribute('src', '/full.webp')
  })

  it('gives a new image a fresh chance after a previous one failed', () => {
    // Otherwise one dead URL would pin the badge to initials for the rest of the session,
    // including after a successful re-upload.
    const { rerender } = render(
      <IdentityBadge initials="AL" name="Ada" avatarThumbUrl="/gone.webp" />,
    )
    fireEvent.error(screen.getByRole('img'))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()

    rerender(<IdentityBadge initials="AL" name="Ada" avatarThumbUrl="/new.webp" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/new.webp')
  })
})
