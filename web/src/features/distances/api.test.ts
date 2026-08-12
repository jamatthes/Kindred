/**
 * distancesApi.recompute — the real `POST /distances/recompute` schema (`RecomputeIn`,
 * `extra = "forbid"`) has no `trip_id` field; the trip is derived server-side from the
 * session's single active trip. Found as a real `422 validation_error` by the M3
 * integration pass's live Playwright smoke, which had been sending `{trip_id,
 * suggestion_id}` per this feature's own (mistaken) mock contract.
 */

import { describe, expect, it, vi } from 'vitest'

const post = vi.fn()
vi.mock('../../app/apiClient', () => ({ api: { post: (...args: unknown[]) => post(...args) } }))

const { distancesApi } = await import('./api')

describe('distancesApi.recompute', () => {
  it('never sends trip_id in the request body, single-suggestion or whole-trip', async () => {
    post.mockResolvedValue({ queued_pairs: 1, estimated_api_calls: 1 })

    await distancesApi.recompute({ trip_id: 't1', suggestion_id: 's1' })
    expect(post).toHaveBeenLastCalledWith('/distances/recompute', { suggestion_id: 's1' })

    await distancesApi.recompute({ trip_id: 't1' })
    expect(post).toHaveBeenLastCalledWith('/distances/recompute', { suggestion_id: undefined })
  })
})
