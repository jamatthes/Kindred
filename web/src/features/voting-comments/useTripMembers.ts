/**
 * The trip's full member roster, for the `@` mention picker (V7: "An autocomplete offers
 * members of the trip").
 *
 * No endpoint in this feature's `design.md` returns that directly — the closest existing
 * surface is `families/design.md`'s `GET /families` (`require_member`, every family
 * coarsely) plus `GET /families/{id}` (`require_member`, one family's full member list).
 * This hook assembles the roster from those two rather than inventing a new endpoint this
 * feature's own contract doesn't define; see the implementation note in
 * `plan/features/voting-comments/design.md`.
 *
 * Fetched once and cached at module scope for the session — a mention picker opening on
 * every keystroke must not re-fetch every family's members each time. The cache is not
 * invalidated on membership-change WS events; a newly-joined member becoming mentionable
 * without a reload is a nice-to-have this pass defers rather than adding a second
 * (untested) invalidation path for a picker that already degrades safely (a stale roster
 * just omits someone very recently added, and the server-side mention validation still
 * refuses to notify an off-trip uuid regardless of what the picker offered).
 */

import { useEffect, useState } from 'react'
import { familiesApi } from '../families/api'
import { familyColor } from '../../design/familyColor'

export type TripMemberOption = {
  userId: string
  displayName: string
  familyId: string | null
  familyColorCss: string | null
}

let cache: TripMemberOption[] | null = null
let inflight: Promise<TripMemberOption[]> | null = null

async function fetchRoster(): Promise<TripMemberOption[]> {
  const families = await familiesApi.list()
  const details = await Promise.all(families.map((f) => familiesApi.read(f.id)))
  const roster: TripMemberOption[] = []
  for (const family of details) {
    for (const member of family.members) {
      roster.push({
        userId: member.user_id,
        displayName: member.display_name,
        familyId: family.id,
        familyColorCss: familyColor(family),
      })
    }
  }
  return roster
}

export function useTripMembers(): TripMemberOption[] {
  const [members, setMembers] = useState<TripMemberOption[]>(cache ?? [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (cache) {
        setMembers(cache)
        return
      }
      inflight ??= fetchRoster()
      try {
        const roster = await inflight
        cache = roster
        if (!cancelled) setMembers(roster)
      } catch {
        // The picker degrades to "no matches" rather than blocking the composer.
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  return members
}

/** Test-only: drops the module cache between test cases. */
export function resetTripMembersCache(): void {
  cache = null
  inflight = null
}
