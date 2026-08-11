/**
 * The app's single socket, plus the React bindings for it.
 *
 * One connection per tab: the server registry keys connections by user, and a second
 * socket would double every broadcast. Features import `socket` and subscribe; nothing
 * else creates a client.
 */

import { useEffect, useState } from 'react'
import { createWsClient } from './wsClient'
import type { WsEnvelope, WsStatus } from './wsClient'

export const socket = createWsClient()

/**
 * Opens the socket while `enabled` is true and closes it otherwise. `enabled` is the
 * session's answer to "is there a user who is allowed one" — an unauthenticated or
 * must-change-password user is refused by the server, so we do not ask.
 */
export function useSocketStatus(enabled: boolean): WsStatus {
  const [status, setStatus] = useState<WsStatus>('idle')

  useEffect(() => {
    const unsubscribe = socket.onStatus(setStatus)
    if (enabled) socket.connect()
    else socket.disconnect()
    return unsubscribe
  }, [enabled])

  return status
}

/** Subscribe to one event type for the lifetime of a component. */
export function useSocketEvent(type: string, handler: (envelope: WsEnvelope) => void): void {
  useEffect(() => socket.subscribe(type, handler), [type, handler])
}
