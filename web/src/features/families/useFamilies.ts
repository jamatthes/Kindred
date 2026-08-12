/**
 * The families list, kept live by the six WebSocket events (FM-12).
 *
 * The events carry the coarse `FamilyOut` and a redacted `MemberOut` — the server will not
 * broadcast an address or a consent state to a room that contains other families. So this
 * store applies what it is given and, for the family the user currently has *open*,
 * refetches the detail: that is the only way to learn the fields the broadcast deliberately
 * omitted, and it is what `design.md` says a client entitled to them should do.
 *
 * "Refetch on notification" rather than "patch from the payload" is also what keeps the
 * client honest about `at-most-once` delivery: the socket says *something changed*, and the
 * server remains the only thing that decides what this viewer may see.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { socket } from '../../app/socket'
import type { WsEnvelope } from '../../app/wsClient'
import type { Family, FamilyDetail } from '../../app/types'
import { familiesApi } from './api'

export type FamiliesState = {
  families: Family[]
  loading: boolean
  error: string | null
  reload: () => void
}

export function useFamilies(): FamiliesState {
  const [families, setFamilies] = useState<Family[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const next = await familiesApi.list()
      setFamilies(next)
      setError(null)
    } catch {
      setError('The families could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const upsert = (envelope: WsEnvelope) => {
      const family = (envelope.payload as { family: Family }).family
      if (!family) return
      setFamilies((current) => {
        const without = current.filter((f) => f.id !== family.id)
        // Sorted by colour, matching the server's `ORDER BY families.color` (NULLS LAST in
        // Postgres), so a family arriving over the socket lands where it would have on a
        // reload rather than at the end. A custom-hex (overflow) family has `color: null`
        // and sorts after every palette slot, same as the server.
        return [...without, family].sort(
          (a, b) => (a.color ?? Number.POSITIVE_INFINITY) - (b.color ?? Number.POSITIVE_INFINITY),
        )
      })
    }

    const drop = (envelope: WsEnvelope) => {
      const id = (envelope.payload as { family_id: string }).family_id
      setFamilies((current) => current.filter((f) => f.id !== id))
    }

    // Member events change counts and roles, neither of which rides on `FamilyOut` in a form
    // this store can patch — so they trigger a reload of the coarse list. Cheap, and it
    // cannot get the count wrong.
    const unsubscribes = [
      socket.subscribe('family.created', upsert),
      socket.subscribe('family.updated', upsert),
      socket.subscribe('family.deleted', drop),
      socket.subscribe('member.joined', () => void load()),
      socket.subscribe('member.removed', () => void load()),
      // `resync` after a reconnect: the server is telling us it replayed nothing.
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  return { families, loading, error, reload: () => void load() }
}

export type FamilyDetailState = {
  family: FamilyDetail | null
  loading: boolean
  error: string | null
  /** Replace the local copy with a response the caller already has. */
  set: (family: FamilyDetail) => void
  reload: () => Promise<void>
}

/** The open family, refetched whenever the socket says it or one of its members changed. */
export function useFamilyDetail(familyId: string | null): FamilyDetailState {
  const [family, setFamily] = useState<FamilyDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Read inside socket handlers, which must not be re-subscribed on every id change.
  const openId = useRef<string | null>(familyId)
  openId.current = familyId

  const load = useCallback(async () => {
    if (!familyId) {
      setFamily(null)
      return
    }
    setLoading(true)
    try {
      setFamily(await familiesApi.read(familyId))
      setError(null)
    } catch {
      setError('That family could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [familyId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const refetchIfOpen = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { family?: { id: string }; family_id?: string }
      const changed = payload.family?.id ?? payload.family_id
      if (changed && changed === openId.current) void load()
    }
    const unsubscribes = [
      socket.subscribe('family.updated', refetchIfOpen),
      socket.subscribe('member.joined', refetchIfOpen),
      socket.subscribe('member.updated', refetchIfOpen),
      socket.subscribe('member.removed', refetchIfOpen),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  return { family, loading, error, set: setFamily, reload: load }
}
