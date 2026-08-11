/**
 * The single door to the REST API.
 *
 * Everything the server promises in `plan/features/foundation/design.md` is handled here
 * once, so no feature has to remember it:
 *
 *  - the `/api/v1` base and JSON encoding/decoding,
 *  - the CSRF double-submit: read the readable `kindred_csrf` cookie and echo it in
 *    `X-CSRF-Token` on every unsafe method (logout included — it is a mutation),
 *  - one retry after a `csrf_invalid`, since a stale cookie is a recoverable condition,
 *  - a typed error carrying the machine-readable `code`, because the UI branches on the
 *    code and shows the server's `message`; it never parses prose.
 *
 * Cookies do the authenticating, so every request is `credentials: 'same-origin'`. In dev
 * the Vite proxy makes the API same-origin; in production Caddy does.
 */

/** Field-level detail attached to a `422 validation_error`. */
export type FieldError = { field: string; message: string }

/**
 * A failed API call. `code` is the contract (`invalid_credentials`, `csrf_invalid`,
 * `stage_forbidden`, …); `message` is the server's human sentence, safe to show.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly errors: FieldError[]
  /** Seconds to wait, from `Retry-After`, when the server rate-limited us. */
  readonly retryAfter: number | null

  constructor(
    status: number,
    code: string,
    message: string,
    errors: FieldError[] = [],
    retryAfter: number | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.errors = errors
    this.retryAfter = retryAfter
  }

  /** The message for a named field, if the server blamed one. */
  fieldError(field: string): string | undefined {
    return this.errors.find((e) => e.field === field)?.message
  }
}

export const CSRF_COOKIE_NAME = 'kindred_csrf'
export const CSRF_HEADER_NAME = 'X-CSRF-Token'

const BASE_URL = '/api/v1'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

/** Codes the client reacts to structurally rather than just displaying. */
export const CODE_CSRF_INVALID = 'csrf_invalid'
export const CODE_NOT_AUTHENTICATED = 'not_authenticated'
export const CODE_PASSWORD_CHANGE_REQUIRED = 'password_change_required'

export function readCookie(name: string): string | null {
  // `document.cookie` is a flat string; splitting on '; ' is the whole parser.
  const prefix = `${name}=`
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length))
  }
  return null
}

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()

/**
 * Called whenever the API says the session is gone. The session store uses this to drop
 * to the login screen from anywhere — including a second tab whose session was revoked by
 * a logout in the first.
 */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

async function parseError(response: Response): Promise<ApiError> {
  const retryAfterHeader = response.headers.get('Retry-After')
  const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : null

  let code = 'unexpected_error'
  let message = 'Something went wrong. Try again.'
  let errors: FieldError[] = []

  try {
    const body = await response.json()
    const detail = body?.detail
    if (detail && typeof detail === 'object') {
      if (typeof detail.code === 'string') code = detail.code
      if (typeof detail.message === 'string') message = detail.message
      if (Array.isArray(detail.errors)) errors = detail.errors as FieldError[]
    }
  } catch {
    // A proxy or a crash can produce a non-JSON body. The status still tells the truth,
    // so fall through with the generic message rather than throwing a parse error at
    // the caller, which would hide what actually happened.
  }

  return new ApiError(
    response.status,
    code,
    message,
    errors,
    Number.isFinite(retryAfter) ? retryAfter : null,
  )
}

type RequestOptions = {
  /** Set false to opt out of the automatic re-auth broadcast (the session bootstrap does). */
  signalUnauthorized?: boolean
  signal?: AbortSignal
}

async function send(
  method: string,
  path: string,
  body: unknown,
  options: RequestOptions,
  isRetry = false,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE_NAME)
    if (csrf) headers[CSRF_HEADER_NAME] = csrf
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  })

  if (response.status === 403 && !isRetry && !SAFE_METHODS.has(method)) {
    // Peek at the code without consuming the caller's response: clone first.
    const probe = await parseError(response.clone())
    if (probe.code === CODE_CSRF_INVALID) {
      // A stale or missing CSRF cookie is recoverable. `auth/me` proves the session is
      // still good and gives the server a chance to reissue the pair; then we retry once.
      // Exactly once — a loop here would hammer the API on a genuine misconfiguration.
      await fetch(`${BASE_URL}/auth/me`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      })
      return send(method, path, body, options, true)
    }
  }

  return response
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  let response: Response
  try {
    response = await send(method, path, body, options)
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') throw cause
    // fetch only rejects for network-level failures; everything else is a status code.
    throw new ApiError(0, 'network_error', 'Kindred could not reach the server.')
  }

  if (response.ok) {
    if (response.status === 204) return undefined as T
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  const error = await parseError(response)

  if (error.status === 401 && options.signalUnauthorized !== false) {
    for (const listener of unauthorizedListeners) listener()
  }

  throw error
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PUT', path, body, options),
  del: <T>(path: string, options?: RequestOptions) =>
    request<T>('DELETE', path, undefined, options),
}
