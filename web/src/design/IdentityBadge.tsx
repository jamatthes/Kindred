/**
 * The identity badge — the one component that renders a person, anywhere in the product.
 *
 * `plan/design-system.md` and `plan/features/families/design.md` both define it here rather
 * than inside `families`, because five places draw it: map markers (`holiday-stage`), member
 * lists, the top-bar presence stack, comment authors (`voting-comments`) and the profile
 * page. Defining it once is what stops the same person looking like two different people on
 * two screens.
 *
 * The rules, all of which are testable:
 *
 * - A circle, holding the avatar image when there is one and the server-computed `initials`
 *   otherwise. `initials` is never derived here — the server computes it so the map, the
 *   member list and the admin console cannot drift.
 * - A 2px ring in the member's `--family-N` token, **always**, image or not. The ring is the
 *   family carrier and is never the only carrier: a name label or `title` always accompanies
 *   it, per the "colour is never the sole signal" rule.
 * - Initials sit on a neutral fill, not the family colour, so contrast does not depend on
 *   which of the eight slots a family happens to hold.
 * - **The badge has no broken state.** A missing, failing or slow image renders the initials
 *   underneath it, so a dead URL degrades to the thing it was standing in for rather than to
 *   a broken-image glyph.
 */

import { useEffect, useState } from 'react'
import './IdentityBadge.css'

/** 24 comment author · 32 member list and presence stack · 40 map marker · 64 profile. */
export type BadgeSize = 24 | 32 | 40 | 64

export type IdentityBadgeProps = {
  initials: string
  /** 1–8. Omitted for someone with no family yet, who gets a neutral ring. */
  familyColor?: number | null
  size?: BadgeSize
  /** 256px rendition. Used at 64; ignored below it, where the thumb is enough. */
  avatarUrl?: string | null
  /** 64px rendition — what everything up to 40px loads. */
  avatarThumbUrl?: string | null
  /** The full name. Always supplied: the ring must never be the only identifier. */
  name?: string
  /** Greys the badge — the presence stack's "nobody in this family is online". */
  offline?: boolean
}

export function IdentityBadge({
  initials,
  familyColor,
  size = 32,
  avatarUrl,
  avatarThumbUrl,
  name,
  offline = false,
}: IdentityBadgeProps) {
  // Everything up to 40px asks for the 64px rendition; only the profile page needs 256.
  const src = size >= 64 ? (avatarUrl ?? avatarThumbUrl) : (avatarThumbUrl ?? avatarUrl)
  const [failed, setFailed] = useState(false)

  // A new src is a new chance: without this, one broken image would pin the badge to
  // initials for the rest of the session even after a successful re-upload.
  useEffect(() => setFailed(false), [src])

  const ring = familyColor ? `var(--family-${familyColor})` : 'var(--color-border-strong)'
  const classes = [
    'k-badge',
    `k-badge--${size}`,
    offline ? 'is-offline' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={classes} style={{ borderColor: ring }} title={name} data-testid="badge">
      {/* The initials are always in the DOM, underneath. An image that fails, or has not
          arrived yet, therefore reveals them rather than a gap. */}
      <span className="k-badge__initials" aria-hidden={src && !failed ? true : undefined}>
        {initials}
      </span>
      {src && !failed ? (
        <img
          className="k-badge__img"
          src={src}
          alt={name ?? ''}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : null}
    </span>
  )
}
