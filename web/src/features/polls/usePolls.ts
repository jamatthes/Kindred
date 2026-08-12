/**
 * The poll list and the open poll, kept live by the WebSocket events.
 *
 * `poll.vote.updated` carries the whole recomputed `PollResults`, so the open poll applies
 * the payload directly rather than refetching — that is the entire point of the server
 * sending the full object, and refetching anyway would waste the design decision.
 *
 * Everything else refetches: the list's completion counts and comment counts are cheap and
 * derived from more than one table, so recomputing them from a delta would be a second
 * implementation of a sum the server already did.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { socket } from '../../app/socket'
import type { WsEnvelope } from '../../app/wsClient'
import type { Poll, PollResults, PollSummary, VotingMode } from '../../app/types'
import { categoryApi, pollsApi } from './api'

export type PollListState = {
  polls: PollSummary[]
  loading: boolean
  error: string | null
  reload: () => void
}

export function usePollList(): PollListState {
  const [polls, setPolls] = useState<PollSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setPolls(await pollsApi.list())
      setError(null)
    } catch {
      setError('The polls could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const refresh = () => void load()
    const unsubscribes = [
      socket.subscribe('poll.created', refresh),
      socket.subscribe('poll.updated', refresh),
      socket.subscribe('poll.deleted', refresh),
      socket.subscribe('poll.closed', refresh),
      socket.subscribe('poll.decided', refresh),
      // A vote elsewhere changes this list's completion counts and nothing else — the
      // design's edge case for a poll that is not the one on screen.
      socket.subscribe('poll.vote.updated', refresh),
      socket.subscribe('comment.created', refresh),
      // After a reconnect the server replays nothing and says so.
      socket.subscribe('resync', refresh),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  return { polls, loading, error, reload: () => void load() }
}

export type PollDetailState = {
  poll: Poll | null
  results: PollResults | null
  loading: boolean
  error: string | null
  setPoll: (poll: Poll) => void
  setResults: (results: PollResults) => void
  reload: () => Promise<void>
}

export function usePollDetail(pollId: string | null): PollDetailState {
  const [poll, setPoll] = useState<Poll | null>(null)
  const [results, setResults] = useState<PollResults | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Read inside socket handlers, which must not resubscribe on every selection change.
  const openId = useRef<string | null>(pollId)
  openId.current = pollId

  const load = useCallback(async () => {
    if (!pollId) {
      setPoll(null)
      setResults(null)
      return
    }
    setLoading(true)
    try {
      const [nextPoll, nextResults] = await Promise.all([
        pollsApi.read(pollId),
        pollsApi.results(pollId),
      ])
      setPoll(nextPoll)
      setResults(nextResults)
      setError(null)
    } catch {
      setError('That poll could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [pollId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const onVote = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { poll_id: string; results: PollResults }
      if (payload.poll_id !== openId.current) return
      // Applied directly: the server sent the entire recomputed object precisely so the
      // matrix, the charts and the map cannot drift from partially applied deltas.
      setResults(payload.results)
    }
    const refetchIfOpen = (envelope: WsEnvelope) => {
      const payload = envelope.payload as { poll_id?: string; poll?: { id: string } }
      const changed = payload.poll_id ?? payload.poll?.id
      if (changed && changed === openId.current) void load()
    }
    const unsubscribes = [
      socket.subscribe('poll.vote.updated', onVote),
      socket.subscribe('poll.updated', refetchIfOpen),
      socket.subscribe('poll.closed', refetchIfOpen),
      socket.subscribe('poll.decided', refetchIfOpen),
      socket.subscribe('poll_option.created', refetchIfOpen),
      socket.subscribe('poll_option.deleted', refetchIfOpen),
      // The trip's voting mode changed under us: the whole control switches between score
      // and thumbs, so a refetch is the only honest response.
      socket.subscribe('category_settings.updated', () => void load()),
      // Somebody left the trip: their column disappears and the counts drop.
      socket.subscribe('member.removed', () => void load()),
      socket.subscribe('stage.changed', () => void load()),
      socket.subscribe('resync', () => void load()),
    ]
    return () => {
      for (const off of unsubscribes) off()
    }
  }, [load])

  return { poll, results, loading, error, setPoll, setResults, reload: load }
}

/** The trip's `poll` voting mode. Never assumed — read, and re-read when it changes. */
export function useVotingMode(): VotingMode {
  const [mode, setMode] = useState<VotingMode>('score')

  const load = useCallback(async () => {
    try {
      const rows = await categoryApi.read()
      const poll = rows.find((row) => row.category === 'poll')
      if (poll) setMode(poll.voting_mode)
    } catch {
      // A failure here must not break the screen; the poll's own `voting_mode` field is
      // authoritative anyway and arrives with the poll.
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => socket.subscribe('category_settings.updated', () => void load()), [load])

  return mode
}
