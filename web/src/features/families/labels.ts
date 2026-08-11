/**
 * The words this feature puts on screen for roles and states.
 *
 * In one module because several of them are quoted verbatim from
 * `plan/features/families/design.md`, and a string that appears in two components will
 * eventually appear in two *different* forms. The location strings especially: they are the
 * only place the three permission inputs are visible together to a person, and their wording
 * was chosen deliberately.
 */

import type { FamilyRole, GeocodeStatus, Member } from '../../app/types'

/** Family-level roles, in the words the product uses rather than the enum's. */
export const ROLE_LABEL: Record<FamilyRole, string> = {
  head: 'Head of family',
  spouse: 'Spouse',
  member: 'Member',
}

/**
 * The five effective-state strings from `design.md`, in the order the rule is evaluated.
 *
 * The fourth and fifth are second-person on purpose: the head or spouse reading this is
 * looking at a consequence of their own action, and the copy should say so rather than
 * reporting a neutral state.
 *
 * NOTE: the first row ("Sharing now") needs a fresh `live_locations` row, which is
 * `holiday-stage`'s to know about and does not exist yet. Until it does, a member whose three
 * permission terms all pass gets the second string — which is true either way, and errs
 * towards *not* claiming someone is visible when they may not be. The indicator must never
 * over-promise.
 */
export function effectiveLocationState(
  member: Member,
  familySharingAllowed: boolean,
): string {
  if (!familySharingAllowed) return 'Off for the whole family'
  if (!member.location_sharing_allowed) return 'You have turned this off for them'
  if (member.location_sharing_enabled === false) return 'Off — only they can turn this on'
  if (member.location_sharing_enabled === null) return 'Only they can see this setting'
  return 'Sharing is on — not visible while the app is closed'
}

/** The four home-address states (FM-3), each with its own text and its own next action. */
export const GEOCODE_STATE: Record<
  GeocodeStatus,
  { title: string; body: string; canRetry: boolean }
> = {
  pending: {
    title: 'No home address yet',
    body: 'Add one so we can show travel times.',
    canRetry: false,
  },
  ok: { title: 'Home address', body: '', canRetry: false },
  not_found: {
    title: 'We could not find that address on the map',
    body: 'Check it and try again.',
    canRetry: true,
  },
  error: {
    title: 'We could not reach the mapping service',
    body: 'Your address is saved.',
    canRetry: true,
  },
}

/** Invite status chips. Words, not colour alone. */
export const INVITE_STATUS_LABEL: Record<string, string> = {
  active: 'Active',
  used: 'Used',
  revoked: 'Revoked',
  expired: 'Expired',
}

const HOURS: Record<number, string> = { 24: '24 hours', 168: '7 days', 720: '30 days' }

export const EXPIRY_CHOICES = [24, 168, 720] as const

export function expiryLabel(hours: number): string {
  return HOURS[hours] ?? `${hours} hours`
}

/** "in 6 days" / "3 hours ago" — enough precision for an invite, and no library. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const ms = new Date(iso).getTime() - now.getTime()
  const abs = Math.abs(ms)
  const day = 86_400_000
  const hour = 3_600_000
  const value = abs >= day ? Math.round(abs / day) : Math.max(1, Math.round(abs / hour))
  const unit = abs >= day ? (value === 1 ? 'day' : 'days') : value === 1 ? 'hour' : 'hours'
  return ms >= 0 ? `in ${value} ${unit}` : `${value} ${unit} ago`
}
