import { beforeEach, describe, expect, it } from 'vitest'
import { hasActiveFilters, suggestionStore } from './store'

describe('suggestionStore', () => {
  beforeEach(() => suggestionStore.reset())

  it('select() is the single shared selection — a map pin and a list row write the same field', () => {
    suggestionStore.select('s1')
    expect(suggestionStore.getState().selectedId).toBe('s1')
    expect(suggestionStore.getState().panelView).toBe('details')

    suggestionStore.select(null)
    expect(suggestionStore.getState().selectedId).toBeNull()
    expect(suggestionStore.getState().panelView).toBe('list')
  })

  it('cycleSort goes asc → desc → original (null), per design-system.md tri-state rule', () => {
    expect(suggestionStore.getState().sort).toBeNull()
    suggestionStore.cycleSort('votes')
    expect(suggestionStore.getState().sort).toEqual({ field: 'votes', dir: 'asc' })
    suggestionStore.cycleSort('votes')
    expect(suggestionStore.getState().sort).toEqual({ field: 'votes', dir: 'desc' })
    suggestionStore.cycleSort('votes')
    expect(suggestionStore.getState().sort).toBeNull()
  })

  it('switching sort field starts a fresh cycle at asc', () => {
    suggestionStore.cycleSort('votes')
    suggestionStore.cycleSort('votes')
    expect(suggestionStore.getState().sort?.dir).toBe('desc')
    suggestionStore.cycleSort('distance')
    expect(suggestionStore.getState().sort).toEqual({ field: 'distance', dir: 'asc' })
  })

  it('toggles filters on and off, and hasActiveFilters reflects any populated list', () => {
    expect(hasActiveFilters(suggestionStore.getState().filters)).toBe(false)
    suggestionStore.toggleType('accommodation')
    expect(suggestionStore.getState().filters.types).toEqual(['accommodation'])
    expect(hasActiveFilters(suggestionStore.getState().filters)).toBe(true)
    suggestionStore.toggleType('accommodation')
    expect(suggestionStore.getState().filters.types).toEqual([])
    expect(hasActiveFilters(suggestionStore.getState().filters)).toBe(false)
  })

  it('clearFilters resets every filter list at once', () => {
    suggestionStore.toggleType('meal')
    suggestionStore.toggleStatus('proposed')
    suggestionStore.toggleFamily('fam-1')
    expect(hasActiveFilters(suggestionStore.getState().filters)).toBe(true)
    suggestionStore.clearFilters()
    expect(suggestionStore.getState().filters).toEqual({
      types: [],
      statuses: [],
      familyIds: [],
      needsMyVote: false,
    })
  })

  it('toggleNeedsMyVote flips the "needs my vote" chip (voting-comments Phase 10)', () => {
    expect(suggestionStore.getState().filters.needsMyVote).toBe(false)
    suggestionStore.toggleNeedsMyVote()
    expect(suggestionStore.getState().filters.needsMyVote).toBe(true)
    expect(hasActiveFilters(suggestionStore.getState().filters)).toBe(true)
    suggestionStore.toggleNeedsMyVote()
    expect(suggestionStore.getState().filters.needsMyVote).toBe(false)
  })

  it('notifies subscribers on every state change', () => {
    let calls = 0
    const unsubscribe = suggestionStore.subscribe(() => {
      calls += 1
    })
    suggestionStore.select('s2')
    suggestionStore.toggleType('activity')
    unsubscribe()
    suggestionStore.toggleType('activity')
    expect(calls).toBe(2)
  })
})
