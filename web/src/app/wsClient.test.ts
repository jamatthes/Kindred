import { afterEach, describe, expect, it, vi } from 'vitest'
import { backoffDelay, createWsClient, socketUrl } from './wsClient'
import type { WsStatus } from './wsClient'

/** A socket we can open, drop and close on demand, with no network anywhere. */
class FakeSocket {
  static instances: FakeSocket[] = []
  static OPEN = 1
  readyState = 0
  onopen: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []

  url: string

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close(code = 1000) {
    this.onclose?.({ code })
  }

  /** Simulate the server accepting the handshake. */
  accept() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.()
  }

  /** Simulate an abnormal drop — the API going away, not a policy refusal. */
  drop(code = 1006) {
    this.onclose?.({ code })
  }
}

describe('socket backoff', () => {
  it('starts at a second and never exceeds thirty', () => {
    for (let attempt = 1; attempt <= 20; attempt++) {
      const min = backoffDelay(attempt, () => 0)
      const max = backoffDelay(attempt, () => 1)
      expect(min).toBe(1_000)
      expect(max).toBeLessThanOrEqual(30_000)
      expect(max).toBeGreaterThanOrEqual(min)
    }
  })

  it('grows the ceiling exponentially until the cap', () => {
    expect(backoffDelay(1, () => 1)).toBe(1_000)
    expect(backoffDelay(2, () => 1)).toBe(2_000)
    expect(backoffDelay(3, () => 1)).toBe(4_000)
    expect(backoffDelay(6, () => 1)).toBe(30_000)
    expect(backoffDelay(12, () => 1)).toBe(30_000)
  })

  it('jitters within the window rather than firing on the same tick', () => {
    // Full jitter: two clients that failed together must not retry together.
    const early = backoffDelay(5, () => 0.1)
    const late = backoffDelay(5, () => 0.9)
    expect(early).toBeLessThan(late)
  })
})

describe('socketUrl', () => {
  it('is at the root, not under /api/v1, and follows the page protocol', () => {
    expect(socketUrl({ protocol: 'http:', host: 'localhost:5173' } as Location)).toBe(
      'ws://localhost:5173/ws',
    )
    expect(socketUrl({ protocol: 'https:', host: 'kindred.example.org' } as Location)).toBe(
      'wss://kindred.example.org/ws',
    )
  })
})

describe('reconnect behaviour', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    FakeSocket.instances = []
  })

  function connectClient() {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeSocket)
    const statuses: WsStatus[] = []
    const client = createWsClient('ws://localhost/ws')
    client.onStatus((status) => statuses.push(status))
    client.connect()
    return { client, statuses, socketAt: (i: number) => FakeSocket.instances[i]! }
  }

  it('stays quiet through the first failure and only then says "reconnecting"', () => {
    const { statuses, socketAt } = connectClient()
    expect(statuses).toEqual(['idle', 'connecting'])

    // First drop: retry silently. One blip is not worth a banner.
    socketAt(0).drop()
    expect(statuses.at(-1)).toBe('connecting')
    expect(statuses).not.toContain('reconnecting')

    vi.advanceTimersByTime(30_000)
    expect(FakeSocket.instances).toHaveLength(2)

    // Second consecutive drop: now tell the user.
    socketAt(1).drop()
    expect(statuses.at(-1)).toBe('reconnecting')
  })

  it('clears the counter once a connection succeeds', () => {
    const { statuses, socketAt } = connectClient()
    socketAt(0).drop()
    vi.advanceTimersByTime(30_000)
    socketAt(1).accept()
    expect(statuses.at(-1)).toBe('open')

    // A later drop starts counting from zero again, so an hour-old failure cannot
    // make the next blip look like a crisis.
    socketAt(1).drop()
    expect(statuses.at(-1)).toBe('connecting')
  })

  it('pings inside the idle timeout and resumes with the last sequence number', () => {
    const { socketAt } = connectClient()
    const socket = socketAt(0)
    socket.accept()
    socket.onmessage?.({ data: JSON.stringify({ type: 'hello', seq: 41, trip_id: 't', ts: '' }) })

    vi.advanceTimersByTime(30_000)
    expect(socket.sent).toContain(JSON.stringify({ type: 'ping' }))

    socket.drop()
    vi.advanceTimersByTime(30_000)
    // The reconnect asks to resume from where it left off; the server answers `resync`.
    expect(socketAt(1).sent).toEqual([])
    socketAt(1).accept()
    expect(socketAt(1).sent).toContain(JSON.stringify({ type: 'resume', last_seq: 41 }))
  })

  it('stops retrying when the server refuses with 1008', () => {
    const { statuses, socketAt } = connectClient()
    // No session, or an outstanding password change: retrying cannot fix either.
    socketAt(0).drop(1008)
    expect(statuses.at(-1)).toBe('unauthorized')

    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.instances).toHaveLength(1)
  })

  it('delivers events to type subscribers and to the wildcard, but never `pong`', () => {
    const { client, socketAt } = connectClient()
    const onResync = vi.fn()
    const onAny = vi.fn()
    client.subscribe('resync', onResync)
    client.subscribe('*', onAny)

    const socket = socketAt(0)
    socket.accept()
    socket.onmessage?.({ data: JSON.stringify({ type: 'resync', seq: 7, trip_id: 't', ts: '' }) })
    socket.onmessage?.({ data: JSON.stringify({ type: 'pong', seq: 7, trip_id: 't', ts: '' }) })
    socket.onmessage?.({ data: 'not json' })

    expect(onResync).toHaveBeenCalledOnce()
    expect(onAny).toHaveBeenCalledOnce()
  })
})
