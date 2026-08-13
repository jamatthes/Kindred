/**
 * The type guess is a preselection the user can override, so the bar it has to clear is
 * "usually right and never absurd" — these cases are the shapes Google actually returns
 * (`types[]` with the useful category first and `point_of_interest`/`establishment` filler
 * behind it), plus the ways it can be useless.
 */

import { describe, expect, it } from 'vitest'
import { DEFAULT_SUGGESTION_TYPE, inferSuggestionType } from './placeType'

describe('inferSuggestionType', () => {
  it('reads the specific category ahead of Google\'s filler entries', () => {
    expect(inferSuggestionType(['lodging', 'point_of_interest', 'establishment'])).toBe('accommodation')
    expect(inferSuggestionType(['restaurant', 'food', 'point_of_interest'])).toBe('meal')
    expect(inferSuggestionType(['museum', 'tourist_attraction', 'establishment'])).toBe('activity')
    expect(inferSuggestionType(['locality', 'political'])).toBe('region')
  })

  it('takes the first entry it recognises, since Google orders most-specific first', () => {
    // A hotel with a restaurant in it comes back lodging-first; the guess must not be
    // decided by whichever category happens to appear later in the array.
    expect(inferSuggestionType(['lodging', 'restaurant', 'establishment'])).toBe('accommodation')
  })

  it('falls back to `other` when nothing is recognised', () => {
    expect(inferSuggestionType(['plumber', 'point_of_interest'])).toBe(DEFAULT_SUGGESTION_TYPE)
    expect(inferSuggestionType([])).toBe(DEFAULT_SUGGESTION_TYPE)
  })

  it('never throws on a missing array', () => {
    expect(inferSuggestionType(undefined)).toBe(DEFAULT_SUGGESTION_TYPE)
    expect(inferSuggestionType(null)).toBe(DEFAULT_SUGGESTION_TYPE)
  })
})
