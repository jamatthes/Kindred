import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, CSRF_HEADER_NAME, api, onUnauthorized } from './apiClient'

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function setCsrfCookie(value: string) {
  document.cookie = `kindred_csrf=${value}; path=/`
}

afterEach(() => {
  vi.restoreAllMocks()
  document.cookie = 'kindred_csrf=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

describe('apiClient', () => {
  it('echoes the CSRF cookie on unsafe methods and omits it on safe ones', async () => {
    setCsrfCookie('token-abc')
    // A fresh Response per call: a body can only be read once.
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(jsonResponse(200, { ok: true })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/auth/logout')
    await api.get('/auth/me')

    const [postUrl, postInit] = fetchMock.mock.calls[0]!
    const [, getInit] = fetchMock.mock.calls[1]!
    const postHeaders = postInit?.headers as Record<string, string>
    const getHeaders = getInit?.headers as Record<string, string>
    expect(postUrl).toBe('/api/v1/auth/logout')
    expect(postHeaders[CSRF_HEADER_NAME]).toBe('token-abc')
    expect(postInit?.credentials).toBe('same-origin')
    // A GET carries no CSRF header: the middleware does not want one, and sending it
    // would imply the token matters on reads.
    expect(getHeaders[CSRF_HEADER_NAME]).toBeUndefined()
  })

  it('retries a csrf_invalid exactly once, behind an auth/me', async () => {
    setCsrfCookie('stale')
    const fetchMock = vi
      .fn()
      // 1: the mutation, rejected for a stale token
      .mockResolvedValueOnce(
        jsonResponse(403, { detail: { code: 'csrf_invalid', message: 'Stale token.' } }),
      )
      // 2: the auth/me that gives the server a chance to reissue
      .mockResolvedValueOnce(jsonResponse(200, { id: 'u1' }))
      // 3: the single retry
      .mockResolvedValueOnce(jsonResponse(200, { saved: true }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.patch('/me/preferences', { theme_pref: 'dark' })).resolves.toEqual({
      saved: true,
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1]![0]).toBe('/api/v1/auth/me')
  })

  it('gives up after one retry rather than looping', async () => {
    setCsrfCookie('stale')
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse(403, { detail: { code: 'csrf_invalid', message: 'Stale token.' } }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.post('/auth/logout')).rejects.toMatchObject({ code: 'csrf_invalid' })
    // mutation, auth/me, retry — and then it stops.
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('throws a typed error carrying the code, message and field errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: {
            code: 'validation_error',
            message: 'Check the form.',
            errors: [{ field: 'new_password', message: 'Choose a new password.' }],
          },
        }),
      ),
    )

    const error = (await api.post('/auth/password', {}).catch((e) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('validation_error')
    expect(error.status).toBe(422)
    expect(error.fieldError('new_password')).toBe('Choose a new password.')
  })

  it('reports Retry-After on a rate limit', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          429,
          { detail: { code: 'rate_limited', message: 'Too many attempts.' } },
          { 'Retry-After': '45' },
        ),
      ),
    )
    const error = (await api.post('/auth/login', {}).catch((e) => e)) as ApiError
    expect(error.retryAfter).toBe(45)
  })

  it('broadcasts a 401 so every tab can drop to login', async () => {
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve(
        jsonResponse(401, { detail: { code: 'not_authenticated', message: 'Log in.' } }),
      ),
    ))
    const listener = vi.fn()
    const unsubscribe = onUnauthorized(listener)

    await api.get('/presence').catch(() => {})
    expect(listener).toHaveBeenCalledOnce()

    // …unless the caller opts out, which the session bootstrap does: a cold load with no
    // cookie is not an event, it is the normal state.
    listener.mockClear()
    await api.get('/auth/me', { signalUnauthorized: false }).catch(() => {})
    expect(listener).not.toHaveBeenCalled()

    unsubscribe()
  })

  it('turns a network failure into an ApiError rather than a raw TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = (await api.get('/settings').catch((e) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('network_error')
  })
})
