/**
 * The broadcast socket.
 *
 * The client never writes over this channel — every mutation goes through REST, so
 * permission checks live in exactly one place. What arrives here is the server telling us
 * something changed, and the only correct reaction is to update or refetch.
 *
 * Behaviours the foundation design pins down:
 *  - connect only after `auth/me` succeeds (an unauthenticated handshake is closed 1008,
 *    and retrying it in a loop would be pointless traffic),
 *  - a user who must change their password is refused the socket, so we do not open one,
 *  - exponential backoff 1s → 30s with jitter, so a restarted API is not thundered,
 *  - the "reconnecting" indicator appears only after the *second* consecutive failure — a
 *    blink during a one-second blip is noise, not information,
 *  - `resume` is answered with `resync` (there is no event log in v1), which means
 *    "refetch what you have open"; subscribers hear that as a first-class signal,
 *  - ping every 30s, comfortably inside the server's 90s idle timeout.
 */

export type WsEnvelope<T = unknown> = {
  type: string
  trip_id: string | null
  seq: number
  ts: string
  payload: T
}

export type WsStatus =
  | 'idle'
  /** Socket opening, including silent early retries. */
  | 'connecting'
  | 'open'
  /** Retrying, and it has gone on long enough to be worth telling the user. */
  | 'reconnecting'
  /** Closed 1008: no session, or the password change is still outstanding. */
  | 'unauthorized'

type Handler = (envelope: WsEnvelope) => void

const PING_INTERVAL_MS = 30_000
const BACKOFF_MIN_MS = 1_000
const BACKOFF_MAX_MS = 30_000
/** Failures before the user is told. One dropped frame is not news; two is. */
const FAILURES_BEFORE_INDICATOR = 2
const WS_CLOSE_POLICY_VIOLATION = 1008
/** Our own code for a deliberate local close, so `onclose` can tell it from a drop. */
const WS_CLOSE_GOING_AWAY = 1000

export function socketUrl(location: Location = window.location): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  // Root path, not /api/v1 — the socket is not a REST resource.
  return `${protocol}//${location.host}/ws`
}

/** Full jitter: spread reconnect attempts so a fleet of tabs does not sync up. */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** Math.max(0, attempt - 1))
  return Math.round(BACKOFF_MIN_MS + random() * (ceiling - BACKOFF_MIN_MS))
}

export type WsClient = ReturnType<typeof createWsClient>

export function createWsClient(url: string = socketUrl()) {
  let socket: WebSocket | null = null
  let pingTimer: ReturnType<typeof setInterval> | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let consecutiveFailures = 0
  let lastSeq = 0
  let wanted = false
  let status: WsStatus = 'idle'

  const handlers = new Map<string, Set<Handler>>()
  const statusListeners = new Set<(status: WsStatus) => void>()

  function setStatus(next: WsStatus) {
    if (status === next) return
    status = next
    for (const listener of statusListeners) listener(next)
  }

  function clearTimers() {
    if (pingTimer !== null) clearInterval(pingTimer)
    if (retryTimer !== null) clearTimeout(retryTimer)
    pingTimer = null
    retryTimer = null
  }

  function dispatch(envelope: WsEnvelope) {
    for (const handler of handlers.get(envelope.type) ?? []) handler(envelope)
    for (const handler of handlers.get('*') ?? []) handler(envelope)
  }

  function open() {
    if (!wanted) return
    setStatus(consecutiveFailures >= FAILURES_BEFORE_INDICATOR ? 'reconnecting' : 'connecting')

    const ws = new WebSocket(url)
    socket = ws

    ws.onopen = () => {
      consecutiveFailures = 0
      setStatus('open')
      // Ask for anything missed. v1 has no event log, so the honest answer is `resync`.
      if (lastSeq > 0) ws.send(JSON.stringify({ type: 'resume', last_seq: lastSeq }))
      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = (event) => {
      let envelope: WsEnvelope
      try {
        envelope = JSON.parse(event.data as string) as WsEnvelope
      } catch {
        return // a frame we cannot parse is a server bug; dropping it beats crashing the tab
      }
      if (typeof envelope?.type !== 'string') return
      if (typeof envelope.seq === 'number' && envelope.seq > lastSeq) lastSeq = envelope.seq
      if (envelope.type === 'pong') return
      dispatch(envelope)
    }

    ws.onclose = (event) => {
      if (pingTimer !== null) clearInterval(pingTimer)
      pingTimer = null
      socket = null

      if (!wanted || event.code === WS_CLOSE_GOING_AWAY) {
        setStatus('idle')
        return
      }

      if (event.code === WS_CLOSE_POLICY_VIOLATION) {
        // No session, or the password change is outstanding. Retrying cannot fix either;
        // the session layer reconnects us once `auth/me` succeeds.
        wanted = false
        setStatus('unauthorized')
        return
      }

      consecutiveFailures += 1
      setStatus(
        consecutiveFailures >= FAILURES_BEFORE_INDICATOR ? 'reconnecting' : 'connecting',
      )
      retryTimer = setTimeout(open, backoffDelay(consecutiveFailures))
    }

    // `onerror` always precedes `onclose`; letting close do the work keeps one retry path.
    ws.onerror = () => {}
  }

  return {
    /** Idempotent: calling it while connected is a no-op, not a second socket. */
    connect() {
      if (wanted && socket !== null) return
      wanted = true
      consecutiveFailures = 0
      clearTimers()
      open()
    },

    disconnect() {
      wanted = false
      clearTimers()
      socket?.close(WS_CLOSE_GOING_AWAY)
      socket = null
      setStatus('idle')
    },

    /**
     * Subscribe to an event type, or to `*` for every event. Returns the unsubscribe.
     * `resync` arrives here like any other type: handle it by refetching.
     */
    subscribe(type: string, handler: Handler): () => void {
      const set = handlers.get(type) ?? new Set<Handler>()
      set.add(handler)
      handlers.set(type, set)
      return () => {
        set.delete(handler)
        if (set.size === 0) handlers.delete(type)
      }
    },

    onStatus(listener: (status: WsStatus) => void): () => void {
      statusListeners.add(listener)
      listener(status)
      return () => statusListeners.delete(listener)
    },

    get status(): WsStatus {
      return status
    },
  }
}
