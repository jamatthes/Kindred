/**
 * A subject's comment thread — `design.md` > "Comment thread" and its WS section.
 *
 * The array from `GET /comments` is always the source of truth for *content*; deletion is
 * layered on top as a client-only UI overlay (`removals`) rather than by splicing the array,
 * which is what makes "undo restores the comment in its original position" true for free —
 * the comment never actually left the array, only its rendered treatment changed:
 *
 *  - **own delete** → `mode: 'undo'`, a ~10s window with an inline undo affordance in place.
 *  - **someone else's delete** (admin moderation, or a WS echo for a delete this client did
 *    not itself initiate) → `mode: 'tombstone'`, permanent for the session, no undo shown.
 *
 * `comment.created` arriving for an id already in `removals` is a restore (`design.md`:
 * "an undo-restore is indistinguishable from a create ... reconciles by id") and clears the
 * overlay; `comment.deleted` for an id not already known locally adds a tombstone rather
 * than removing the row, so position is preserved for every other viewer too.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { socket } from '../../app/socket'
import type { WsEnvelope } from '../../app/wsClient'
import type { Comment, CommentSubjectType } from '../../app/types'
import { commentsApi } from './api'

/** The undo affordance's visible window. Shorter than the server's retention window
 * (target 30 days, `design.md`) on purpose — retention is a safety margin, not a feature. */
export const UNDO_WINDOW_MS = 10_000

export type Removal = { mode: 'undo' | 'tombstone'; expiresAt: number | null; performedByMe: boolean }

export type CommentThreadState = {
  comments: Comment[]
  removals: Map<string, Removal>
  loading: boolean
  error: string | null
  post: (body: string) => Promise<boolean>
  edit: (id: string, body: string) => Promise<boolean>
  remove: (id: string) => Promise<boolean>
  undo: (id: string) => Promise<boolean>
  reload: () => Promise<void>
}

function upsertById(list: Comment[], next: Comment): Comment[] {
  const index = list.findIndex((c) => c.id === next.id)
  if (index === -1) return [...list, next]
  const copy = list.slice()
  copy[index] = next
  return copy
}

export function useCommentThread(
  subjectType: CommentSubjectType,
  subjectId: string | null,
): CommentThreadState {
  const [comments, setComments] = useState<Comment[]>([])
  const [removals, setRemovals] = useState<Map<string, Removal>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const subjectRef = useRef(subjectId)
  subjectRef.current = subjectId
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const load = useCallback(async () => {
    if (!subjectId) {
      setComments([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      setComments(await commentsApi.list(subjectType, subjectId))
      setRemovals(new Map())
      setError(null)
    } catch {
      setError('The comments could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [subjectType, subjectId])

  useEffect(() => {
    void load()
    return () => {
      // Deliberately reads `.current` at cleanup time, not a snapshot: this ref holds a
      // `Map` of in-flight undo timers (not a DOM node), and unmounting must clear
      // whichever timers exist *then*, not whichever existed when the effect ran.
      /* eslint-disable react-hooks/exhaustive-deps */
      for (const timer of timers.current.values()) clearTimeout(timer)
      timers.current.clear()
      /* eslint-enable react-hooks/exhaustive-deps */
    }
  }, [load])

  const finalizeRemoval = useCallback((id: string) => {
    setRemovals((current) => {
      if (!current.has(id)) return current
      const next = new Map(current)
      next.delete(id)
      return next
    })
    setComments((current) => current.filter((c) => c.id !== id))
    timers.current.delete(id)
  }, [])

  useEffect(() => {
    const matchesSubject = (payload: { subject_type?: string; subject_id?: string }) =>
      !payload.subject_type || !payload.subject_id
        ? true // no subject fields on the payload: assume relevant rather than silently drop
        : payload.subject_type === subjectType && payload.subject_id === subjectRef.current

    // `comment.created`/`comment.updated` broadcasts nest the actual comment under `comment`
    // alongside the subject fields (`server/app/routers/comments.py`'s `_broadcast` calls) —
    // unlike `comment.deleted`, which is flat. Found by the M3 integration pass's live
    // Playwright smoke: casting the envelope straight to `Comment` produced an object with no
    // `id`/`body`/`author`, which crashed `upsertById` callers reading those fields.
    const onCreated = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { subject_type?: string; subject_id?: string; comment: Comment }
      if (!matchesSubject(payload)) return
      const comment = payload.comment
      setComments((current) => upsertById(current, comment))
      // A restore (undo-delete broadcasts comment.created, design.md) clears the overlay.
      setRemovals((current) => {
        if (!current.has(comment.id)) return current
        const next = new Map(current)
        next.delete(comment.id)
        return next
      })
      const timer = timers.current.get(comment.id)
      if (timer) {
        clearTimeout(timer)
        timers.current.delete(comment.id)
      }
    }
    const onUpdated = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { subject_type?: string; subject_id?: string; comment: Comment }
      if (!matchesSubject(payload)) return
      setComments((current) => upsertById(current, payload.comment))
    }
    const onDeleted = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { id: string; subject_type?: string; subject_id?: string }
      if (!matchesSubject(payload)) return
      setRemovals((current) => {
        if (current.has(payload.id)) return current // already tracked locally
        const next = new Map(current)
        next.set(payload.id, { mode: 'tombstone', expiresAt: null, performedByMe: false })
        return next
      })
    }

    const unsubscribes = [
      socket.subscribe('comment.created', onCreated),
      socket.subscribe('comment.updated', onUpdated),
      socket.subscribe('comment.deleted', onDeleted),
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [subjectType, load])

  async function post(body: string): Promise<boolean> {
    if (!subjectId || !body.trim()) return false
    setError(null)
    try {
      const comment = await commentsApi.create(subjectType, subjectId, body.trim())
      setComments((current) => upsertById(current, comment))
      return true
    } catch {
      setError('That comment could not be posted.')
      return false
    }
  }

  async function edit(id: string, body: string): Promise<boolean> {
    setError(null)
    try {
      const comment = await commentsApi.update(id, body.trim())
      setComments((current) => upsertById(current, comment))
      return true
    } catch {
      setError('That edit could not be saved.')
      return false
    }
  }

  async function remove(id: string): Promise<boolean> {
    setError(null)
    const comment = comments.find((c) => c.id === id)
    const performedByMe = comment?.can_edit ?? false // only the author can edit; delete-undo is author-only too
    try {
      await commentsApi.remove(id)
      const expiresAt = performedByMe ? Date.now() + UNDO_WINDOW_MS : null
      setRemovals((current) => {
        const next = new Map(current)
        next.set(id, { mode: performedByMe ? 'undo' : 'tombstone', expiresAt, performedByMe })
        return next
      })
      if (performedByMe) {
        const timer = setTimeout(() => finalizeRemoval(id), UNDO_WINDOW_MS)
        timers.current.set(id, timer)
      }
      return true
    } catch {
      setError('That comment could not be deleted.')
      return false
    }
  }

  async function undo(id: string): Promise<boolean> {
    setError(null)
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
    try {
      const comment = await commentsApi.undoDelete(id)
      setComments((current) => upsertById(current, comment))
      setRemovals((current) => {
        const next = new Map(current)
        next.delete(id)
        return next
      })
      return true
    } catch {
      setError('Too late to undo — that comment is gone.')
      // Finalize locally too: the retention window has closed server-side.
      finalizeRemoval(id)
      return false
    }
  }

  return { comments, removals, loading, error, post, edit, remove, undo, reload: load }
}
